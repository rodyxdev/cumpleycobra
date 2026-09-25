"""API de Cumple&Cobra (FastAPI). Fase 1: plantilla fija, motor de cuatro capas y release.

Arranque (desde la raíz del repositorio):
    backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000
"""

import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.from_thread
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool
from stellar_sdk import StrKey

from . import drafting, gemini
from .config import (
    GEMINI_ATTEMPT_BUDGET_SECS,
    MAX_DEADLINE_MINUTES,
    MAX_SUBMISSIONS,
    MIN_SECONDS_TO_EVALUATE,
    RELEASE_BUDGET_SECS,
    load_settings,
)
from .deterministic import analyze
from .hashing import code_hash, rules_hash, verdict_hash
from .fx import FxReference
from .video import normalize_video
from .plantilla import DEMO_RAW_REQUEST, DEMO_SPEC
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


class CreateTaskIn(Strict):
    client_address: StrictStr
    raw_request: StrictStr = Field(default="", max_length=2000)
    description: drafting.Description
    criteria: list[drafting.Criterion] = Field(min_length=1, max_length=8)
    language: StrictStr
    allowed_deps: list[StrictStr] = Field(default=[], max_length=drafting.MAX_ALLOWED_DEPS)
    examples: list[drafting.Example] = Field(default=[], max_length=drafting.MAX_EXAMPLES)
    amount: StrictInt = Field(gt=0)
    # 7 días: muy lejos del TTL de 30 días que el contrato extiende en cada escritura.
    deadline_minutes: StrictInt = Field(gt=0, le=MAX_DEADLINE_MINUTES)


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
fx_reference = FxReference()
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
        "message": f"Solicitud inválida en '{where}': revisa el tipo, la longitud y los campos requeridos.",
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


class ClockUnavailable(Exception):
    """No se pudo leer el reloj del ledger: es un error de red, no falta de plazo."""


async def seconds_left(deadline: int) -> int | None:
    """Segundos de plazo on-chain, o None si el RPC no responde (sin reloj no se decide nada)."""
    try:
        now = await run_in_threadpool(chain().ledger_time)
    except StellarUnavailable:
        return None
    return deadline - now


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/fx/usd-mxn")
async def fx_usd_mxn():
    return await fx_reference.get()


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


@app.post("/tasks/draft", response_model=drafting.Draft)
async def draft_task(body: drafting.DraftIn):
    try:
        return await drafting.draft(app.state.gemini, app.state.settings.gemini_model, body.raw_request)
    except gemini.EngineUnavailable as exc:
        raise err(502, "ENGINE_UNAVAILABLE", "No se pudo preparar el pedido. Inténtalo de nuevo o usa la plantilla de la demo.") from exc


@app.post("/tasks/draft/review", response_model=drafting.Review)
async def review_draft(body: drafting.ReviewIn):
    try:
        return await drafting.review(app.state.gemini, app.state.settings.gemini_model, body.criteria)
    except gemini.EngineUnavailable as exc:
        raise err(502, "ENGINE_UNAVAILABLE", "No se pudieron revisar los criterios. Inténtalo de nuevo.") from exc


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
        "latest_code_hash": task.get("latest_code_hash"),
        "consented_code_hash": task.get("consented_code_hash"),
        "latest_rejected": bool(task.get("latest_code_hash") and not task["codes"][task["latest_code_hash"]].get("approved")),
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
        # Sin trustline de USDC el release fallaría: se bloquea antes de aceptar.
        try:
            has_trustline = await run_in_threadpool(chain().has_usdc_trustline, body.freelancer_address)
        except StellarUnavailable as exc:
            raise err(502, "CHAIN_UNAVAILABLE", f"No se pudo revisar la trustline ({exc})") from exc
        if not has_trustline:
            raise err(409, "NO_USDC_TRUSTLINE",
                      "Tu cuenta no tiene trustline de USDC. Actívala antes de aceptar la tarea.")
        if not bound:
            task["freelancer_address"] = body.freelancer_address
            task["freelancer_token"] = secrets.token_urlsafe(32)
            task["accepted_at"] = int(time.time())
            store().save()
        return {"freelancer_token": task["freelancer_token"]}


CASOS_DIR = Path(__file__).resolve().parent / "casos"
CASOS = [  # mismos archivos que usa scripts/fase1-curl.sh
    {"id": "A", "nombre": "Caso A: implementación correcta", "archivo": "a_feliz.py", "principal": True},
    {"id": "B", "nombre": "Caso B: bucle sin incremento", "archivo": "b_calidad.py", "principal": True},
    {"id": "C", "nombre": "Caso C: inyección en el docstring", "archivo": "c_inyeccion.py", "principal": True},
    {"id": "D", "nombre": "Caso D: lectura de secretos", "archivo": "d_secretos.py", "principal": False},
]


@app.get("/demo")
async def demo():
    """Plantilla fija y casos de la demo (fuente única: backend/plantilla.py y backend/casos/)."""
    return {
        "raw_request": DEMO_RAW_REQUEST,
        "spec": DEMO_SPEC,
        "casos": [{"id": c["id"], "nombre": c["nombre"], "principal": c["principal"],
                   "codigo": (CASOS_DIR / c["archivo"]).read_text(encoding="utf-8")} for c in CASOS],
    }


@app.get("/tasks/{task_id}/verdicts")
async def verdicts(task_id: str, x_client_token: str | None = Header(default=None)):
    """Veredictos para la vista del cliente: reason, comparison y security_flags (nunca trace, logic ni código)."""
    task = get_task_or_404(task_id)
    if not token_ok(task["client_token"], x_client_token):
        raise err(403, "INVALID_TOKEN", "Token de cliente inválido")
    return {
        "task_id": task_id,
        "submissions_used": len(task["submissions"]),
        "verdicts": [
            {"code_hash": r["code_hash"], "approved": r["approved"], "stage": r["stage"],
             "reason": r["reason"], "comparison": r["comparison"],
             # El mismo aviso de seguridad que ve el programador (y el que entra al verdict_hash).
             "security_flags": r.get("security_flags", []),
             "transaction_hash": r["transaction_hash"],
             "video_url": task["codes"].get(r["code_hash"], {}).get("video_url"),
             "consented": task.get("consented_code_hash") == r["code_hash"]}
            for r in task["cache"].values()
        ],
    }


@app.get("/tasks/{task_id}/delivery")
async def delivery(task_id: str, x_client_token: str | None = Header(default=None)):
    task = get_task_or_404(task_id)
    if not token_ok(task["client_token"], x_client_token):
        raise err(403, "INVALID_TOKEN", "Token de cliente inválido")
    onchain, _ = await read_chain(task_id)
    released = onchain and onchain["status"] == "Released"
    if released:
        paid_hash = (task.get("release") or {}).get("code_hash")
        approved = [c for c in task["codes"].values() if c.get("approved")]
        chosen = task["codes"].get(paid_hash) or (approved[-1] if approved else (list(task["codes"].values()) or [None])[-1])
    else:
        consented = task.get("consented_code_hash")
        chosen = task["codes"].get(consented)
        if not chosen or chosen.get("approved"):
            raise err(409, "TASK_NOT_RELEASED", "El código se entrega al cobrar o con consentimiento del programador para una entrega rechazada")
    if chosen is None:
        raise err(404, "NO_DELIVERY", "No hay código entregado")
    return {"task_id": task_id, "code": chosen["code"], "video_url": chosen.get("video_url"),
            "code_hash": chosen["code_hash"]}


class ConsentIn(Strict):
    code_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


@app.post("/tasks/{task_id}/consent")
async def consent(task_id: str, body: ConsentIn | None = None,
                  x_freelancer_token: str | None = Header(default=None)):
    task = get_task_or_404(task_id)
    async with store().lock(task_id):
        if not token_ok(task.get("freelancer_token"), x_freelancer_token):
            raise err(403, "INVALID_TOKEN", "Token de programador inválido")
        ch = body.code_hash if body else task.get("latest_code_hash")
        code = task["codes"].get(ch)
        if not code or code.get("approved"):
            raise err(409, "NO_REJECTED_DELIVERY", "Solo se puede autorizar la revisión de una entrega rechazada")
        task["consented_code_hash"] = ch
        store().save()
        return {"code_hash": ch, "consented": True}


# ---------------------------------------------------------------------------
# /evaluate
# ---------------------------------------------------------------------------
REASON_DEADLINE_PASSED = (
    "El código cumple los criterios acordados, pero el plazo del contrato venció antes de "
    "liberar el pago, así que no se pagó automáticamente. El cliente aún puede aprobarlo "
    "manualmente."
)
REASON_NO_TRUSTLINE = (
    "El pago no se liberó: la dirección del programador no tiene trustline de USDC. Cuando la "
    "active, el cliente puede aprobar el pago manualmente."
)
REASON_PAID_OTHERWISE = "La tarea ya se pagó por otra entrega o por aprobación manual."
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

        try:
            video_url = normalize_video(body.video_url)
        except ValueError as exc:
            raise err(400, "INVALID_REQUEST", str(exc)) from exc

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
                left = await seconds_left(deadline)
                if left is None:
                    raise ClockUnavailable()
                return left >= GEMINI_ATTEMPT_BUDGET_SECS

            try:
                gv, _elapsed = await gemini.evaluate(app.state.gemini, app.state.settings.gemini_model,
                                                     spec, det.clean_code, time_ok)
            except gemini.OutOfTime:
                raise err(409, "DEADLINE_TOO_CLOSE",
                          "No queda plazo para reintentar el análisis; el envío no se contó") from None
            except ClockUnavailable:
                raise err(502, "CHAIN_UNAVAILABLE",
                          "No se pudo leer el reloj del contrato para reintentar el análisis; "
                          "el envío no se contó") from None
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
                          video_url=video_url)
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
            "video_url": video_url,  # el mismo valor normalizado que entra al verdict_hash
            "payment_retryable": False,
        }
        task["codes"][ch] = {"code": body.code, "video_url": video_url, "code_hash": ch,
                             "approved": approved}
        task["latest_code_hash"] = ch

        counted = True
        if approved:
            left = await seconds_left(deadline)
            if left is None:
                network_error(result)  # sin reloj: se reintenta con el mismo código
            elif left < RELEASE_BUDGET_SECS:
                result["reason"] = REASON_NO_TIME_TO_RELEASE
                counted = False
            else:
                # El veredicto queda en caché (y en disco) antes de firmar: si el proceso cae durante
                # el release, reenviar el mismo código reintenta el pago en vez de volver a evaluar.
                result["payment_retryable"] = True
                task["cache"][ch] = result
                store().save()
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
    if rel and rel.get("status") == "success" and rel.get("code_hash") == result["code_hash"]:
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
        if await trustline_missing(freelancer):
            no_trustline(result)
            return
        result["reason"] = f"{result['verdict_reason']} El pago no se liberó (error del contrato #{exc.code})."
        result["payment_retryable"] = False
        return
    except StellarUnavailable:
        if await trustline_missing(freelancer):
            no_trustline(result)
            return
        network_error(result)
        return

    if outcome.status == "success":
        task["release"]["status"] = "success"
        result["transaction_hash"] = outcome.transaction_hash
        result["reason"] = result["verdict_reason"]
        result["payment_retryable"] = False
    else:
        await settle_not_funded(task, result)


async def settle_not_funded(task: dict, result: dict) -> None:
    """#6 o release sin confirmar: solo es éxito si el release guardado es de esta entrega y quedó SUCCESS.

    Que la tarea esté Released para el programador no basta: pudo pagarla otra entrega o el cliente
    con client_release, y entonces este veredicto no tiene transacción propia.
    """
    try:
        onchain = await run_in_threadpool(chain().get_task, task["task_id"])
    except (StellarUnavailable, ContractError):
        onchain = None
    rel = task.get("release")
    if onchain and onchain["status"] == "Released":
        own = (rel and rel.get("code_hash") == result["code_hash"]
               and onchain.get("freelancer") == task["freelancer_address"])
        confirmed = False
        if own:
            try:
                confirmed = await run_in_threadpool(chain().transaction_succeeded, rel["transaction_hash"])
            except StellarUnavailable:
                network_error(result)  # sin confirmar todavía: el reenvío lo vuelve a revisar
                return
        if own and confirmed:
            rel["status"] = "success"
            result["transaction_hash"] = rel["transaction_hash"]
            result["reason"] = result["verdict_reason"]
            result["payment_retryable"] = False
            return
        result["transaction_hash"] = None
        result["reason"] = f"{result['verdict_reason']} {REASON_PAID_OTHERWISE}"
        result["payment_retryable"] = False
        return
    state = onchain["status"] if onchain else "desconocido"
    if state == "Funded":
        # El contrato solo acepta release con timestamp < plazo: vencido, ya no hay reintento posible.
        left = await seconds_left(onchain["deadline"])
        if left is not None and left <= 0:
            result["reason"] = REASON_DEADLINE_PASSED
            result["payment_retryable"] = False
            return
    if state == "Funded" and await trustline_missing(task["freelancer_address"]):
        no_trustline(result)
        return
    result["reason"] = (f"{result['verdict_reason']} El pago no se liberó: la tarea on-chain está en "
                        f"estado {state}.")
    result["payment_retryable"] = state == "Funded"


async def trustline_missing(address: str) -> bool:
    """True solo si se pudo confirmar que falta la trustline (un error de red no cuenta)."""
    try:
        return not await run_in_threadpool(chain().has_usdc_trustline, address)
    except Exception:  # noqa: BLE001
        return False


def network_error(result: dict) -> None:
    """Fallo de red (RPC o reloj del ledger): el mismo código se puede reenviar sin contar envío."""
    result["reason"] = (f"{result['verdict_reason']} El pago no se pudo enviar por un problema de red; "
                        "reenvía el mismo código para reintentarlo (no cuenta como envío).")
    result["payment_retryable"] = True


def no_trustline(result: dict) -> None:
    """Falta la trustline: no es un fallo de red, así que no se marca como reintentable."""
    result["reason"] = f"{result['verdict_reason']} {REASON_NO_TRUSTLINE}"
    result["payment_retryable"] = False
