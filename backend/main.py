"""API de Cumple&Cobra (FastAPI). Fase 1: plantilla fija, motor de cuatro capas y release.

Arranque (desde la raíz del repositorio):
    backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000
"""

import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager

import anyio.from_thread
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool
from stellar_sdk import StrKey

from . import gemini
from .config import (
    GEMINI_ATTEMPT_BUDGET_SECS,
    MAX_SUBMISSIONS,
    MIN_SECONDS_TO_EVALUATE,
    RELEASE_BUDGET_SECS,
    load_settings,
)
from .deterministic import analyze
from .hashing import code_hash, rules_hash, verdict_hash
from .state import StateStore
from .stellar_client import (
    ERR_DEADLINE_PASSED,
    ERR_NOT_FUNDED,
    ContractError,
    StellarClient,
    StellarUnavailable,
)

log = logging.getLogger("cumpleycobra")


# ---------------------------------------------------------------------------
# Errores con el formato {"error": "CODIGO", "message": "..."}
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def err(status: int, code: str, message: str) -> ApiError:
    return ApiError(status, code, message)


# ---------------------------------------------------------------------------
# Modelos de entrada (enteros estrictos: nunca float en montos ni plazos)
# ---------------------------------------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Example(Strict):
    input: StrictStr
    output: StrictStr


class CreateTaskIn(Strict):
    client_address: StrictStr
    raw_request: StrictStr = ""
    description: StrictStr = Field(min_length=1)
    criteria: list[StrictStr] = Field(min_length=1)
    language: StrictStr
    allowed_deps: list[StrictStr] = []
    examples: list[Example] = []
    amount: StrictInt = Field(gt=0)
    deadline_minutes: StrictInt = Field(gt=0, le=60 * 24 * 30)


class AcceptIn(Strict):
    freelancer_address: StrictStr
    invite_token: StrictStr


class EvaluateIn(Strict):
    task_id: StrictStr
    freelancer_address: StrictStr
    code: StrictStr
    video_url: StrictStr | None = None


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    app.state.store = StateStore(settings.state_file)
    app.state.chain = StellarClient(settings)
    app.state.gemini = gemini.make_client(settings)
    log.info("Backend listo: %r", settings)
    yield


settings_for_cors = load_settings()
app = FastAPI(title="Cumple&Cobra", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings_for_cors.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Client-Token", "X-Freelancer-Token"],
)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    codes = {400: "INVALID_REQUEST", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    return JSONResponse(status_code=exc.status_code, content={
        "error": codes.get(exc.status_code, "HTTP_ERROR"),
        "message": "Solicitud inválida: el cuerpo no es JSON válido en UTF-8"
        if exc.status_code == 400 else str(exc.detail),
    })


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return JSONResponse(status_code=400, content={
        "error": "INVALID_REQUEST",
        "message": f"Solicitud inválida en '{where}': {first.get('msg', '')}",
    })


def store() -> StateStore:
    return app.state.store


def chain() -> StellarClient:
    return app.state.chain


def token_ok(expected: str | None, given: str | None) -> bool:
    if not expected or not given:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())


def check_address(addr: str, field: str) -> None:
    if not StrKey.is_valid_ed25519_public_key(addr):
        raise err(400, "INVALID_REQUEST", f"'{field}' no es una dirección Stellar válida (G...)")


def get_task_or_404(task_id: str) -> dict:
    task = store().tasks.get(task_id)
    if task is None:
        raise err(404, "TASK_NOT_FOUND", "No existe esa tarea")
    return task


async def read_chain(task_id: str) -> tuple[dict | None, int]:
    """Tarea on-chain y timestamp del ledger. 502 si el RPC no responde."""
    try:
        onchain = await run_in_threadpool(chain().get_task, task_id)
        now = await run_in_threadpool(chain().ledger_time)
    except (StellarUnavailable, ContractError) as exc:
        raise err(502, "CHAIN_UNAVAILABLE", f"No se pudo leer el contrato ({exc})") from exc
    return onchain, now


async def seconds_left(deadline: int) -> int:
    try:
        now = await run_in_threadpool(chain().ledger_time)
    except StellarUnavailable:
        return 0  # sin reloj confiable no se arriesga el pago
    return deadline - now


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/tasks")
async def create_task(body: CreateTaskIn):
    check_address(body.client_address, "client_address")
    if body.language != "python":
        raise err(400, "INVALID_REQUEST", "Por ahora el único lenguaje soportado es 'python'")
    criteria = [c.strip() for c in body.criteria if c.strip()]
    if not criteria:
        raise err(400, "INVALID_REQUEST", "Debe haber al menos un criterio")

    spec = {
        "description": body.description,
        "criteria": criteria,
        "language": body.language,
        "allowed_deps": sorted(set(body.allowed_deps)),
        "examples": [e.model_dump() for e in body.examples],
    }
    task_id = secrets.token_urlsafe(12)
    task = {
        "task_id": task_id,
        "created_at": int(time.time()),
        "client_address": body.client_address,
        "raw_request": body.raw_request,
        "spec": spec,
        "rules_hash": rules_hash(spec),
        "amount": body.amount,
        "deadline_minutes": body.deadline_minutes,
        "client_token": secrets.token_urlsafe(32),
        "invite_token": secrets.token_urlsafe(32),
        "freelancer_address": None,
        "freelancer_token": None,
        "accepted_at": None,
        "submissions": [],
        "cache": {},
        "codes": {},
        "release": None,
    }
    store().tasks[task_id] = task
    store().save()
    return {
        "task_id": task_id,
        "rules_hash": task["rules_hash"],
        "client_token": task["client_token"],
        "invite_token": task["invite_token"],
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = get_task_or_404(task_id)
    onchain, left, chain_error = None, None, None
    try:
        onchain, now = await read_chain(task_id)
        if onchain:
            left = onchain["deadline"] - now
    except ApiError as exc:
        chain_error = exc.message
    return {
        "task_id": task_id,
        "raw_request": task["raw_request"],
        **task["spec"],
        "rules_hash": task["rules_hash"],
        "amount": task["amount"],
        "deadline_minutes": task["deadline_minutes"],
        "client_address": task["client_address"],
        "freelancer_address": task["freelancer_address"],
        "submissions_used": len(task["submissions"]),
        "max_submissions": MAX_SUBMISSIONS,
        "onchain": onchain,
        "seconds_left": left,
        "onchain_error": chain_error,
    }


@app.post("/tasks/{task_id}/accept")
async def accept(task_id: str, body: AcceptIn):
    task = get_task_or_404(task_id)
    check_address(body.freelancer_address, "freelancer_address")
    async with store().lock(task_id):
        if not token_ok(task["invite_token"], body.invite_token):
            raise err(403, "INVALID_TOKEN", "La invitación no es válida para esta tarea")
        bound = task["freelancer_address"]
        if bound and bound != body.freelancer_address:
            raise err(409, "TASK_TAKEN", "Esta tarea ya la aceptó otro programador")
        if not bound:
            task["freelancer_address"] = body.freelancer_address
            task["freelancer_token"] = secrets.token_urlsafe(32)
            task["accepted_at"] = int(time.time())
            store().save()
        return {"freelancer_token": task["freelancer_token"]}


@app.get("/tasks/{task_id}/delivery")
async def delivery(task_id: str, x_client_token: str | None = Header(default=None)):
    task = get_task_or_404(task_id)
    if not token_ok(task["client_token"], x_client_token):
        raise err(403, "INVALID_TOKEN", "Token de cliente inválido")
    onchain, _ = await read_chain(task_id)
    if not onchain or onchain["status"] != "Released":
        raise err(409, "TASK_NOT_RELEASED", "El código se entrega cuando el programador cobra")
    approved = [c for c in task["codes"].values() if c.get("approved")]
    chosen = approved[-1] if approved else (list(task["codes"].values()) or [None])[-1]
    if chosen is None:
        raise err(404, "NO_DELIVERY", "No hay código entregado")
    return {"task_id": task_id, "code": chosen["code"], "video_url": chosen.get("video_url"),
            "code_hash": chosen["code_hash"]}


# ---------------------------------------------------------------------------
# /evaluate
# ---------------------------------------------------------------------------
REASON_DEADLINE_PASSED = (
    "El código cumple los criterios acordados, pero el plazo del contrato venció antes de "
    "liberar el pago, así que no se pagó automáticamente. El cliente aún puede aprobarlo "
    "manualmente."
)
REASON_NO_TIME_TO_RELEASE = (
    "El código cumple los criterios acordados, pero no queda plazo suficiente para liberar el "
    "pago de forma segura. El envío no se contó. El cliente aún puede aprobarlo manualmente."
)


def comparison_placeholder(spec: dict, why: str) -> list[str]:
    return [f"✗ Criterio {i}: no evaluado; {why}" for i in range(1, len(spec["criteria"]) + 1)]


@app.post("/evaluate")
async def evaluate(body: EvaluateIn, x_freelancer_token: str | None = Header(default=None)):
    task = get_task_or_404(body.task_id)
    spec = task["spec"]
    async with store().lock(body.task_id):
        # --- Guardias ----------------------------------------------------------
        if not task["freelancer_address"]:
            raise err(409, "CRITERIA_NOT_ACCEPTED", "Ningún programador ha aceptado los criterios")
        if (not token_ok(task["freelancer_token"], x_freelancer_token)
                or body.freelancer_address != task["freelancer_address"]):
            raise err(403, "INVALID_TOKEN", "Token de programador inválido para esta tarea")

        ch = code_hash(body.code)
        cached = task["cache"].get(ch)
        if cached is not None:
            if cached["approved"] and cached["transaction_hash"] is None and cached.get("payment_retryable"):
                # Veredicto aprobado cuyo pago falló por red: se reintenta sin contar envío.
                onchain, now = await read_chain(body.task_id)
                if onchain and onchain["status"] == "Funded":
                    if onchain["deadline"] - now >= RELEASE_BUDGET_SECS:
                        await try_payment(task, cached)
                    else:
                        cached["reason"] = REASON_NO_TIME_TO_RELEASE
                        cached["payment_retryable"] = False
                else:
                    await settle_not_funded(task, cached)
                store().save()
            return {**public(cached), "stage": "cache", "submissions_used": len(task["submissions"])}

        if len(task["submissions"]) >= MAX_SUBMISSIONS:
            raise err(429, "TOO_MANY_SUBMISSIONS", f"Ya se usaron los {MAX_SUBMISSIONS} envíos de esta tarea")

        onchain, now = await read_chain(body.task_id)
        if not onchain or onchain["status"] != "Funded":
            raise err(409, "TASK_NOT_FUNDED", "La tarea no está depositada en el contrato")
        if (onchain["amount"] != task["amount"] or onchain["client"] != task["client_address"]
                or onchain["rules_hash"] != task["rules_hash"]):
            raise err(409, "TASK_MISMATCH", "El monto, el cliente o los criterios on-chain no coinciden")
        deadline = onchain["deadline"]
        if deadline - now < MIN_SECONDS_TO_EVALUATE:
            raise err(409, "DEADLINE_TOO_CLOSE",
                      f"Quedan menos de {MIN_SECONDS_TO_EVALUATE} s de plazo; ya no se puede evaluar")

        # --- Capas 1 y 2: higiene y determinista ---------------------------------
        det = analyze(body.code, spec["allowed_deps"])
        if not det.ok:
            stage, approved = "deterministic", False
            reason = det.reason
            security_flags = det.problems if det.security else []
            analysis = list(det.problems)
            comparison = comparison_placeholder(spec, "el código fue rechazado por la capa determinista")
        else:
            # --- Capa 3: Gemini ---------------------------------------------------
            async def time_ok() -> bool:
                return await seconds_left(deadline) >= GEMINI_ATTEMPT_BUDGET_SECS

            try:
                gv, _elapsed = await gemini.evaluate(app.state.gemini, app.state.settings.gemini_model,
                                                     spec, det.clean_code, time_ok)
            except gemini.OutOfTime:
                raise err(409, "DEADLINE_TOO_CLOSE",
                          "No queda plazo para reintentar el análisis; el envío no se contó") from None
            except gemini.EngineUnavailable as exc:
                raise err(502, "ENGINE_UNAVAILABLE",
                          f"El motor de análisis no respondió; el envío no se contó ({exc})") from None

            # --- Capa 4: regla final del backend ----------------------------------
            stage = "llm"
            security_flags = list(gv.security_flags)
            comparison = list(gv.comparison)
            all_met = all(c.lstrip().startswith("✓") for c in comparison)
            approved = gv.approved and not security_flags and all_met
            reason = gv.reason
            if gv.approved and security_flags:
                reason = "Rechazado por seguridad: " + "; ".join(security_flags)
            elif gv.approved and not all_met:
                reason = "Rechazado: el motor marcó al menos un criterio como no cumplido. " + gv.reason
            analysis = list(gv.trace) + list(gv.logic) + comparison

        vh = verdict_hash(task_id=body.task_id, code_hash=ch, approved=approved, reason=reason,
                          stage=stage, comparison=comparison, security_flags=security_flags,
                          video_url=body.video_url)
        result = {
            "task_id": body.task_id,
            "approved": approved,
            "reason": reason,
            "transaction_hash": None,
            "stage": stage,
            "analysis": analysis,
            "comparison": comparison,
            "code_hash": ch,
            "verdict_hash": vh,
            "verdict_reason": reason,
            "security_flags": security_flags,
            "payment_retryable": False,
        }
        task["codes"][ch] = {"code": body.code, "video_url": body.video_url, "code_hash": ch,
                             "approved": approved}

        counted = True
        if approved:
            if await seconds_left(deadline) < RELEASE_BUDGET_SECS:
                result["reason"] = REASON_NO_TIME_TO_RELEASE
                counted = False
            else:
                await try_payment(task, result)

        if counted:
            task["submissions"].append({"code_hash": ch, "stage": stage, "approved": approved,
                                        "at": int(time.time())})
        task["cache"][ch] = result
        store().save()
        return {**public(result), "submissions_used": len(task["submissions"])}


def public(result: dict) -> dict:
    hidden = {"verdict_reason", "payment_retryable"}
    return {k: v for k, v in result.items() if k not in hidden}


async def try_payment(task: dict, result: dict) -> None:
    """Paso 9: release al programador amarrado. Actualiza `result` en su lugar."""
    task_id = task["task_id"]
    freelancer = task["freelancer_address"]
    rel = task.get("release")
    if rel and rel.get("status") == "success":
        result["transaction_hash"] = rel["transaction_hash"]
        result["payment_retryable"] = False
        return

    def on_signed(tx_hash: str) -> None:
        def save() -> None:
            task["release"] = {"status": "pending", "transaction_hash": tx_hash,
                               "freelancer": freelancer, "code_hash": result["code_hash"],
                               "verdict_hash": result["verdict_hash"]}
            store().save()
        anyio.from_thread.run_sync(save)

    try:
        outcome = await run_in_threadpool(chain().release, task_id, freelancer,
                                          result["code_hash"], result["verdict_hash"], on_signed)
    except ContractError as exc:
        if exc.code == ERR_DEADLINE_PASSED:
            result["reason"] = REASON_DEADLINE_PASSED
            result["payment_retryable"] = False
            return
        if exc.code == ERR_NOT_FUNDED:
            await settle_not_funded(task, result)
            return
        result["reason"] = f"{result['verdict_reason']} El pago no se liberó (error del contrato #{exc.code})."
        result["payment_retryable"] = False
        return
    except StellarUnavailable:
        result["reason"] = (f"{result['verdict_reason']} El pago no se pudo enviar por un problema de red; "
                            "reenvía el mismo código para reintentarlo (no cuenta como envío).")
        result["payment_retryable"] = True
        return

    if outcome.status == "success":
        task["release"]["status"] = "success"
        result["transaction_hash"] = outcome.transaction_hash
        result["reason"] = result["verdict_reason"]
        result["payment_retryable"] = False
    else:
        await settle_not_funded(task, result)


async def settle_not_funded(task: dict, result: dict) -> None:
    """#6 o release sin confirmar: si la tarea ya está Released para este programador, es éxito."""
    try:
        onchain = await run_in_threadpool(chain().get_task, task["task_id"])
    except (StellarUnavailable, ContractError):
        onchain = None
    rel = task.get("release")
    if (onchain and onchain["status"] == "Released"
            and onchain.get("freelancer") == task["freelancer_address"] and rel):
        rel["status"] = "success"
        result["transaction_hash"] = rel["transaction_hash"]
        result["reason"] = result["verdict_reason"]
        result["payment_retryable"] = False
        return
    state = onchain["status"] if onchain else "desconocido"
    result["reason"] = (f"{result['verdict_reason']} El pago no se liberó: la tarea on-chain está en "
                        f"estado {state}.")
    result["payment_retryable"] = state == "Funded"
