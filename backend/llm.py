"""Adaptador de modelos para el verificador (fase 3): un rol, un proveedor elegido por variable.

Roles: `suite` (genera los tests ocultos) y `juez` (decide criterio por criterio con evidencia).
Proveedores:
- `gemini` (por defecto): el mismo cliente de v1 (Vertex AI o AI Studio), con `response_json_schema`.
- `muse`: Muse Spark de Meta, API compatible con OpenAI (`MODEL_API_KEY`, `MODEL_BASE_URL`,
  `MUSE_MODEL`), con `response_format=json_schema` estricto. Se llama con httpx, sin otro SDK.

Variables por rol: `LLM_SUITE_PROVIDER`, `LLM_JUEZ_PROVIDER` (`gemini` | `muse`) y, opcionales,
`LLM_SUITE_MODEL`, `LLM_JUEZ_MODEL`. Nunca se imprimen las credenciales.

`structured()` devuelve una instancia validada del modelo Pydantic pedido, o lanza `LLMError`.
Reintentos: 2 ante errores transitorios (timeout, 429, 5xx) con espera de 1 y 3 s, y 1 ante una
respuesta fuera de esquema.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("cumpleycobra.llm")

T = TypeVar("T", bound=BaseModel)
Role = Literal["suite", "juez"]
PROVIDERS = ("gemini", "muse")
BACKOFF_SECS = (1, 3)
DEFAULT_TIMEOUT_SECS = 90


class LLMError(RuntimeError):
    """El modelo no devolvió una respuesta válida tras los reintentos."""


@dataclass
class Usage:
    role: str
    provider: str
    model: str
    seconds: float
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0


def provider_for(role: Role) -> tuple[str, str]:
    """(proveedor, modelo) configurados para un rol."""
    provider = (os.environ.get(f"LLM_{role.upper()}_PROVIDER") or "gemini").strip().lower()
    if provider not in PROVIDERS:
        raise LLMError(f"LLM_{role.upper()}_PROVIDER debe ser uno de: {', '.join(PROVIDERS)}")
    default = os.environ.get("GEMINI_MODEL", "") if provider == "gemini" else os.environ.get("MUSE_MODEL", "muse-spark-1.3")
    model = os.environ.get(f"LLM_{role.upper()}_MODEL") or default
    if not model:
        raise LLMError(f"Falta el modelo para el rol {role}")
    return provider, model


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema de Pydantic en modo estricto: sin propiedades extra y todas requeridas."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        node.pop("default", None)
        for key, value in node.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                for sub in value.values():
                    walk(sub)
            else:
                walk(value)

    walk(schema)
    return schema


def _parse(raw: str | None, output: type[T]) -> T | None:
    if not raw:
        return None
    try:
        return output.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None


# --- Gemini ---------------------------------------------------------------------------------

async def _gemini_call(client, model: str, system: str, turns: list[dict], output: type[BaseModel],
                       timeout: float) -> tuple[str | None, int, int]:
    from google.genai import types

    contents = [types.Content(role="model" if t["role"] == "assistant" else "user",
                              parts=[types.Part(text=t["content"])]) for t in turns]
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=strict_json_schema(output),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )
    resp = await asyncio.wait_for(
        client.aio.models.generate_content(model=model, contents=contents, config=config), timeout=timeout)
    meta = getattr(resp, "usage_metadata", None)
    return resp.text, getattr(meta, "prompt_token_count", 0) or 0, getattr(meta, "candidates_token_count", 0) or 0


def _gemini_transient(exc: Exception) -> bool:
    from google.genai import errors as genai_errors

    if isinstance(exc, genai_errors.APIError):
        return exc.code == 429 or (exc.code is not None and exc.code >= 500)
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, asyncio.TimeoutError, TimeoutError))


# --- Muse Spark (API compatible con OpenAI) -----------------------------------------------

class _HttpStatus(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


async def _muse_call(model: str, system: str, turns: list[dict], output: type[BaseModel],
                     timeout: float) -> tuple[str | None, int, int]:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise LLMError("Falta MODEL_API_KEY para el proveedor muse")
    base = (os.environ.get("MODEL_BASE_URL") or "https://api.meta.ai/v1").rstrip("/")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *turns],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": output.__name__, "schema": strict_json_schema(output), "strict": True}},
    }
    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
    if resp.status_code >= 400:
        raise _HttpStatus(resp.status_code)
    data = resp.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length" or choice["message"].get("refusal"):
        return None, 0, 0
    usage = data.get("usage") or {}
    return choice["message"].get("content"), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def _muse_transient(exc: Exception) -> bool:
    if isinstance(exc, _HttpStatus):
        return exc.status in (408, 409, 429) or exc.status >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, asyncio.TimeoutError, TimeoutError))


# --- Punto de entrada ----------------------------------------------------------------------

async def structured(role: Role, system: str, turns: list[dict], output: type[T], *,
                     gemini_client=None, timeout: float = DEFAULT_TIMEOUT_SECS,
                     usage: list[Usage] | None = None) -> T:
    """Pide al modelo del rol una respuesta conforme a `output`.

    `turns` = [{"role": "user" | "assistant", "content": str}, ...] (sin el mensaje de sistema).
    """
    provider, model = provider_for(role)
    if provider == "gemini" and gemini_client is None:
        raise LLMError("No hay cliente de Gemini configurado")
    started = time.monotonic()
    transient = schema = 0
    attempt = 0
    while True:
        attempt += 1
        try:
            if provider == "gemini":
                raw, tin, tout = await _gemini_call(gemini_client, model, system, turns, output, timeout)
            else:
                raw, tin, tout = await _muse_call(model, system, turns, output, timeout)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - se clasifica abajo
            is_transient = _gemini_transient(exc) if provider == "gemini" else _muse_transient(exc)
            log.warning("LLM %s/%s: intento %d falló (%s)", role, provider, attempt, type(exc).__name__)
            if is_transient and transient < len(BACKOFF_SECS):
                await asyncio.sleep(BACKOFF_SECS[transient])
                transient += 1
                continue
            raise LLMError(f"El modelo ({provider}) no respondió: {type(exc).__name__}") from exc
        parsed = _parse(raw, output)
        if parsed is not None:
            if usage is not None:
                usage.append(Usage(role, provider, model, round(time.monotonic() - started, 2), attempt, tin, tout))
            return parsed
        log.warning("LLM %s/%s: intento %d fuera de esquema", role, provider, attempt)
        if schema < 1:
            schema += 1
            continue
        raise LLMError(f"El modelo ({provider}) respondió fuera del esquema dos veces")
