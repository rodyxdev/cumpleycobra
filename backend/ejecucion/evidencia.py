"""Evidencia del perfil web: capturas de la entrega (fase 3).

La VM del verificador no tiene credenciales, así que manda las capturas a la API junto con la
evidencia, y la API las guarda:
- en Cloud Storage si hay `EVIDENCE_BUCKET` (con la cuenta de servicio de la API; el bucket tiene una
  regla de retención de 90 días), o
- en una carpeta local (`EVIDENCE_DIR`, por defecto `.data/evidencia`) en desarrollo.

Las capturas no son públicas: se ven con una URL firmada de 15 minutos, que la API genera cada vez
que el programador o el cliente consultan la verificación (con su token). La firma es un HMAC con
una llave derivada de `VERIFIER_QUEUE_TOKEN` (separada por dominio: no sirve como token de la cola).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path

import httpx

log = logging.getLogger("cumpleycobra.evidencia")

URL_TTL_SECS = 15 * 60
KEY_RE = re.compile(r"^tareas/[A-Za-z0-9_-]{4,64}/[A-Za-z0-9_-]{4,64}/S[0-9]{1,3}\.jpg$")
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
STORAGE = "https://storage.googleapis.com"


class EvidenceError(RuntimeError):
    pass


def _signing_key() -> bytes:
    token = os.environ.get("VERIFIER_QUEUE_TOKEN") or ""
    if not token:
        raise EvidenceError("falta VERIFIER_QUEUE_TOKEN para firmar las URLs de la evidencia")
    return hmac.new(token.encode(), b"cyc-evidencia-url-v1", hashlib.sha256).digest()


def sign(key: str, now: float | None = None, ttl: int = URL_TTL_SECS) -> str:
    """Ruta firmada (relativa a la API) para ver una captura durante `ttl` segundos."""
    exp = int((now if now is not None else time.time()) + ttl)
    sig = hmac.new(_signing_key(), f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"/evidencia/{urllib.parse.quote(key)}?exp={exp}&sig={sig}"


def verify(key: str, exp: int, sig: str, now: float | None = None) -> bool:
    if not KEY_RE.fullmatch(key) or exp < (now if now is not None else time.time()):
        return False
    expected = hmac.new(_signing_key(), f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def screenshot_key(task_id: str, job_id: str, shot_id: str) -> str:
    key = f"tareas/{task_id}/{job_id}/{shot_id}.jpg"
    if not KEY_RE.fullmatch(key):
        raise EvidenceError(f"clave de evidencia inválida: {key!r}")
    return key


class LocalStore:
    def __init__(self, root: Path):
        self.root = root

    async def put(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.is_file() else None


class GcsStore:
    """Cloud Storage por su API JSON, con las credenciales de la API (ADC). Sin SDK extra."""

    def __init__(self, bucket: str, credentials=None, transport: httpx.AsyncBaseTransport | None = None):
        self.bucket, self._credentials, self._transport = bucket, credentials, transport

    async def _headers(self) -> dict:
        from starlette.concurrency import run_in_threadpool

        if self._credentials is None:
            import google.auth

            self._credentials, _ = await run_in_threadpool(google.auth.default, scopes=[SCOPE])
        if not self._credentials.valid:
            from google.auth.transport.requests import Request

            await run_in_threadpool(self._credentials.refresh, Request())
        return {"Authorization": f"Bearer {self._credentials.token}"}

    async def put(self, key: str, data: bytes) -> None:
        url = f"{STORAGE}/upload/storage/v1/b/{self.bucket}/o"
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as http:
            resp = await http.post(url, params={"uploadType": "media", "name": key}, content=data,
                                   headers={**await self._headers(), "Content-Type": "image/jpeg"})
        if resp.status_code >= 400:
            raise EvidenceError(f"Cloud Storage respondió {resp.status_code} al guardar la evidencia")

    async def get(self, key: str) -> bytes | None:
        url = f"{STORAGE}/storage/v1/b/{self.bucket}/o/{urllib.parse.quote(key, safe='')}"
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as http:
            resp = await http.get(url, params={"alt": "media"}, headers=await self._headers())
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise EvidenceError(f"Cloud Storage respondió {resp.status_code} al leer la evidencia")
        return resp.content


def make_store():
    bucket = (os.environ.get("EVIDENCE_BUCKET") or "").strip()
    if bucket:
        return GcsStore(bucket)
    root = Path(os.environ.get("EVIDENCE_DIR") or Path(__file__).resolve().parents[2] / ".data" / "evidencia")
    return LocalStore(root)


def public_screenshots(screenshots: list[dict], now: float | None = None) -> list[dict]:
    """Metadatos de las capturas con su URL firmada (para la respuesta de la API)."""
    out = []
    for shot in screenshots:
        item = {k: shot[k] for k in ("id", "page", "viewport", "label", "sha256") if k in shot}
        if shot.get("key"):
            try:
                item["url"] = sign(shot["key"], now)
            except EvidenceError:
                item["url"] = None
        out.append(item)
    return out
