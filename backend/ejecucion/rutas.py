"""Rutas del verificador por ejecución (fase 3). Todas responden 404 sin `VERIFIER_ENABLED`.

Del trabajador (header `Authorization: Bearer <VERIFIER_QUEUE_TOKEN>` y el `lease_id` del trabajo):
    POST /verifier/claim                      → un trabajo o 204
    POST /verifier/jobs/{id}/progress         → avance (renueva el plazo del trabajo)
    POST /verifier/jobs/{id}/suite/generate   → tests candidatos de la siguiente ronda
    POST /verifier/jobs/{id}/suite/validation → resultados contra la entrega vacía y el stub
    GET  /verifier/jobs/{id}/source           → el ZIP de la entrega
    POST /verifier/jobs/{id}/result           → evidencia; la API juzga, decide y paga
    POST /verifier/jobs/{id}/fail             → el verificador no pudo ejecutar (no cuenta envío)

Públicas:
    GET  /tasks/{id}/suite                    → plan de la suite (sin código de los tests)
    POST /tasks/{id}/verificaciones           → encola una entrega (header X-Freelancer-Token)
    GET  /verificaciones/{id}                 → avance y veredicto (X-Freelancer-Token o X-Client-Token)
    GET  /evidencia/{clave}?exp=&sig=          → una captura del perfil web (URL firmada de 15 min)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import re
import time
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import MAX_PASTE_BYTES, MAX_ZIP_BYTES, VERIFY_MIN_SECONDS, enabled, queue_token
from . import arranque, evidencia, perfil
from . import suite as suite_mod
from . import web as web_mod
from .cola import LeaseError
from .juez import EvidenceChecker, judge
from .juez_web import WebEvidenceChecker, judge_web
from .regla import decide, decide_web
from .seguridad import security_scan
from .senales import collect_signals, load_sources, output_signals
from .. import hitos
from ..hashing import verdict_hash_v2
from ..limites import client_ip, rate_limiter
from ..llm import LLMError, Usage

router = APIRouter()
log = logging.getLogger("cumpleycobra.verificador")

SUITE_JOB_ATTEMPTS = 3
REPO_RE = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"


def api():
    from .. import main  # import tardío: main importa este módulo al arrancar

    return main


def guard_enabled() -> None:
    if not enabled():
        raise api().err(404, "NOT_FOUND", "La verificación por ejecución no está habilitada")


def queue():
    return api().app.state.queue


def guard_worker(authorization: str | None) -> None:
    guard_enabled()
    expected = queue_token()
    if not expected:
        raise api().err(503, "VERIFIER_NOT_CONFIGURED", "Falta VERIFIER_QUEUE_TOKEN en la API")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not given or not hmac.compare_digest(expected.encode(), given.encode()):
        raise api().err(403, "INVALID_TOKEN", "Token de la cola inválido")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeaseIn(Strict):
    lease_id: StrictStr = Field(max_length=100)


class ProgressIn(LeaseIn):
    stage: StrictStr = Field(max_length=40)
    detail: StrictStr = Field(default="", max_length=300)


class RunIn(BaseModel):
    report_found: bool
    outcomes: list[dict] = Field(default=[], max_length=500)
    stderr_tail: str = ""
    timed_out: bool = False


class WebRunIn(BaseModel):
    report_found: bool
    checks: dict = Field(default={})
    stderr_tail: str = ""
    timed_out: bool = False
    errors: list = Field(default=[], max_length=50)


class ValidationIn(LeaseIn):
    # Perfil script: corridas contra la entrega vacía, el stub y la referencia.
    empty: RunIn | None = None
    stub: RunIn | None = None
    reference: RunIn | None = None
    # Perfil web: el navegador contra un sitio vacío y contra el sitio de referencia.
    web_empty: WebRunIn | None = None
    web_reference: WebRunIn | None = None


class ResultIn(LeaseIn):
    evidence: dict


class FailIn(LeaseIn):
    message: StrictStr = Field(max_length=500)


def leased(job_id: str, lease_id: str) -> dict:
    job = queue().get(job_id)
    if not job or job["status"] != "running" or not hmac.compare_digest((job["lease_id"] or "").encode(), lease_id.encode()):
        raise api().err(409, "LEASE_INVALID", "El trabajo no está asignado a este verificador")
    return job


def execution_spec(spec: dict) -> dict:
    return perfil.execution_spec(spec)


# --- ciclo de la suite: límites, arranque, recuperación y reintento ----------------------

MAX_SUITE_RETRIES = 2        # reintentos que puede pedir el cliente tras una suite rechazada
SUITE_GRACE_SECS = 30        # tras encolar, no se "recupera" una suite que apenas empezó


def _limit(name: str) -> int:
    try:
        return max(0, int((os.environ.get(name) or "0").strip()))
    except ValueError:
        return 0


def admit_suite(ip: str) -> None:
    """Antes de preparar una suite (hasta 8 llamadas al modelo y tiempo de la VM, antes del depósito).

    1. Si ya hay `MAX_PENDING_SUITES` suites en cola o corriendo: 503 VERIFIER_BUSY.
    2. Ventana por IP (`RATE_LIMIT_SUITES_PER_MINUTE`).
    3. Cuota diaria global `RATE_LIMIT_DAILY_SUITE` (se consume al final: un rechazo no gasta cuota).
    Sin variables no hay límite (modo local); `demo` y `live` fijan valores por defecto.
    """
    cap = _limit("MAX_PENDING_SUITES")
    if cap:
        stats = queue().stats()
        if stats["queued"].get("suite", 0) + stats["running"].get("suite", 0) >= cap:
            raise api().err(503, "VERIFIER_BUSY",
                            "El verificador está preparando muchas tareas a la vez. Inténtalo en unos minutos.")
    refused = rate_limiter.check_ip(ip, _limit("RATE_LIMIT_SUITES_PER_MINUTE"), "suite")
    if refused:
        raise refused
    rate_limiter.consume_daily("suite")


def start_suite(task: dict, milestone: int | None = None) -> None:
    """Suite nueva (o reiniciada) y su trabajo en la cola. Quien llama guarda el estado."""
    target = hitos.target_for(task, milestone)
    spec = target["spec"]
    target["suite"] = web_mod.new_suite_state(spec) if spec.get("web") else suite_mod.new_suite_state(spec)
    target["suite"]["started_at"] = time.time()
    payload = {"spec": execution_spec(spec)}
    if milestone is not None:
        payload["milestone"] = milestone
    target["suite_job"] = queue().enqueue("suite", task["task_id"], payload)["id"]


def _suite_jobs(task: dict, milestone: int | None = None) -> list[dict]:
    """Trabajos de la suite vigente (los de antes de un reintento del cliente no cuentan)."""
    target = hitos.target_for(task, milestone)
    since = target["suite"].get("started_at", 0)
    return [j for j in queue().for_task(task["task_id"])
            if j["kind"] == "suite" and j["payload"].get("milestone") == milestone and j["created_at"] >= since - 1]


def _suite_gave_up(suite: dict, detail: str) -> None:
    suite["status"] = "rechazada"
    suite["error"] = detail[:300]
    suite["error_public"] = "El verificador no estuvo disponible; no es un problema de tu acuerdo. Puedes pedir otro intento"


async def reconcile_suite(task: dict, milestone: int | None = None) -> None:
    """Recupera una suite sin trabajo activo (p. ej. la VM Spot se detuvo tres veces y el plazo del
    trabajo venció sin pasar por /fail): la reencola o, agotados los intentos, la marca rechazada
    para que el cliente pueda pedir otro intento. Sin esto la tarea se queda «preparando» para siempre."""
    target = hitos.target_for(task, milestone)
    suite = target.get("suite")
    if not arranque.suite_waiting(suite) or time.time() - suite.get("started_at", 0) < SUITE_GRACE_SECS:
        return
    if any(j["status"] in ("queued", "running") for j in _suite_jobs(task, milestone)):
        return
    m = api()
    async with m.store().lock(task["task_id"]):
        target = hitos.target_for(task, milestone)
        if not arranque.suite_waiting(target["suite"]):
            return
        jobs = _suite_jobs(task, milestone)
        if any(j["status"] in ("queued", "running") for j in jobs):
            return
        if len(jobs) < SUITE_JOB_ATTEMPTS:
            payload = {"spec": execution_spec(target["spec"])}
            if milestone is not None:
                payload["milestone"] = milestone
            target["suite_job"] = queue().enqueue("suite", task["task_id"], payload)["id"]
            log.warning("suite de %s sin trabajo activo: se reencola (%d de %d)", task["task_id"], len(jobs) + 1,
                        SUITE_JOB_ATTEMPTS)
        else:
            _suite_gave_up(target["suite"], "el trabajo de la suite venció sin respuesta del verificador")
            log.warning("suite de %s sin trabajo activo y sin intentos: rechazada", task["task_id"])
        m.store().save()


# --- trabajador ------------------------------------------------------------------------

@router.post("/verifier/claim")
async def claim(authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = queue().claim()
    if job is None:
        return Response(status_code=204)
    payload = job["payload"]
    if job["kind"] == "verify":
        task = api().get_task_or_404(job["task_id"])
        target = hitos.target_for(task, payload.get("milestone"))
        # Los tests (o los chequeos web) se leen al reclamar: siempre la suite vigente de la tarea o hito.
        payload = {**payload, "tests": dict(target["suite"]["files"])}
        if target["suite"].get("profile") == "web":
            payload["checks"] = web_mod.accepted_checks(target["suite"])
    return {"id": job["id"], "kind": job["kind"], "lease_id": job["lease_id"], "payload": payload}


@router.post("/verifier/jobs/{job_id}/progress")
async def progress(job_id: str, body: ProgressIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    try:
        queue().progress(job_id, body.lease_id, {"stage": body.stage, "detail": body.detail})
    except LeaseError:
        raise api().err(409, "LEASE_INVALID", "El trabajo no está asignado a este verificador") from None
    return {"ok": True}


def _validate_step(target: dict) -> dict | None:
    """Lo que el verificador debe validar ahora (o None si no hay nada pendiente con archivos)."""
    suite = target["suite"]
    if suite.get("profile") == "web":
        checks = web_mod.to_validate(suite)
        if not checks:
            return None
        return {"next": "validate", "profile": "web", "round": suite["round"], "pages": target["spec"]["web"]["pages"],
                "checks": checks, "reference_site": suite.get("reference_site")}
    to_check = {c["index"] for c in suite_mod.pending(suite)} & {suite_mod.criterion_index(f) for f in suite["files"]}
    if not to_check:
        return None
    return {"next": "validate", "round": suite["round"], "tests": dict(suite["files"]),
            "reference": suite.get("reference")}


async def _advance_suite(job_id: str, lease_id: str, target: dict) -> dict:
    """Genera rondas hasta tener algo que validar o terminar. Quien llama tiene el candado de la tarea."""
    m = api()
    suite = target["suite"]
    mod = perfil.suite_module(suite)
    while True:
        queue().progress(job_id, lease_id, {"stage": "suite", "detail": f"generando la ronda {suite['round'] + 1}"})
        try:
            await mod.generate_round(target["spec"], suite, m.app.state.gemini)
        except LLMError as exc:
            suite["status"] = "rechazada"
            suite["error"] = str(exc)[:300]
            suite["error_public"] = "El modelo no respondió al preparar la verificación; no es un problema de tu acuerdo"
            m.store().save()
            queue().finish(job_id, lease_id, "failed", {"error": suite["error"]})
            return {"next": "done"}
        step = _validate_step(target)
        if step:
            m.store().save()
            return step
        # Nada nuevo que validar: todo era lectura (o visual), o la ronda solo dejó problemas estáticos.
        if mod.pending(suite) and suite["round"] <= mod.MAX_REGENERATIONS:
            suite["status"] = "pendiente"
            continue
        mod.finalize(suite)
        m.store().save()
        queue().finish(job_id, lease_id, "done", mod.public_plan(suite))
        return {"next": "done"}


@router.post("/verifier/jobs/{job_id}/suite/generate")
async def suite_generate(job_id: str, body: LeaseIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    m = api()
    task = m.get_task_or_404(job["task_id"])
    milestone = job["payload"].get("milestone")
    async with m.store().lock(task["task_id"]):
        target = hitos.target_for(task, milestone)
        step = _validate_step(target) if target["suite"]["status"] == "validando" else None
        if step:
            # Un trabajo anterior generó esta ronda y el verificador falló al validarla: se reanuda
            # la validación sin volver a pedirle tests al modelo.
            return step
        return await _advance_suite(job_id, body.lease_id, target)


@router.post("/verifier/jobs/{job_id}/suite/validation")
async def suite_validation(job_id: str, body: ValidationIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    m = api()
    task = m.get_task_or_404(job["task_id"])
    milestone = job["payload"].get("milestone")
    async with m.store().lock(task["task_id"]):
        target = hitos.target_for(task, milestone)
        suite = target["suite"]
        if suite.get("profile") == "web":
            if body.web_empty is None:
                raise m.err(400, "INVALID_REQUEST", "Falta web_empty para validar la suite web")
            again = web_mod.apply_validation(suite, body.web_empty.model_dump(),
                                             body.web_reference.model_dump() if body.web_reference else None)
        else:
            if body.empty is None or body.stub is None:
                raise m.err(400, "INVALID_REQUEST", "Faltan empty y stub para validar la suite")
            again = suite_mod.apply_validation(suite, body.empty.model_dump(), body.stub.model_dump(),
                                               body.reference.model_dump() if body.reference else None)
        m.store().save()
        if again:
            return await _advance_suite(job_id, body.lease_id, target)
    queue().finish(job_id, body.lease_id, "done", perfil.public_plan(target["suite"]))
    return {"next": "done"}


@router.get("/verifier/jobs/{job_id}/source")
async def source(job_id: str, lease_id: str, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, lease_id)
    src = job["payload"]["source"]
    data = queue().get_source(src.get("source_id", "")) if src["kind"] == "zip" else None
    if data is None:
        raise api().err(404, "NO_DELIVERY", "Este trabajo no tiene un ZIP")
    return Response(content=data, media_type="application/zip")


@router.post("/verifier/jobs/{job_id}/fail")
async def fail(job_id: str, body: FailIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    queue().finish(job_id, body.lease_id, "failed", {"error": body.message})
    if job["kind"] == "suite":
        # Falla de infraestructura, no de la suite: se reintenta con otro trabajo (hasta 3 en total).
        m = api()
        task = m.get_task_or_404(job["task_id"])
        milestone = job["payload"].get("milestone")
        async with m.store().lock(task["task_id"]):
            target = hitos.target_for(task, milestone)
            if job["id"] != target.get("suite_job") or not arranque.suite_waiting(target["suite"]):
                return {"ok": True}  # trabajo de una suite anterior (el cliente pidió otro intento)
            tries = len(_suite_jobs(task, milestone))
            if tries < SUITE_JOB_ATTEMPTS:
                target["suite_job"] = queue().enqueue("suite", task["task_id"], job["payload"])["id"]
            else:
                _suite_gave_up(target["suite"], f"el verificador no pudo ejecutar la suite: {body.message[:200]}")
            m.store().save()
    return {"ok": True}


def _outcomes_by_criterion(outcomes: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for o in outcomes:
        index = suite_mod.criterion_index(o.get("file", ""))
        if index:
            grouped.setdefault(index, []).append(o)
    return grouped


def _as_code(files: dict[str, str], source: dict) -> str:
    """Texto que se entrega al cliente en `code` (compatible con `/delivery` de v1)."""
    if source.get("kind") == "code":
        return source["code"]
    return "\n".join(f"# --- {rel} ---\n{text}" for rel, text in files.items())


@router.post("/verifier/jobs/{job_id}/result")
async def result(job_id: str, body: ResultIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    m = api()
    task = m.get_task_or_404(job["task_id"])
    ev = body.evidence
    async with m.store().lock(task["task_id"]):
        if ev.get("error") == "ingest":
            queue().finish(job_id, body.lease_id, "failed",
                           {"error": "INGEST_FAILED", "message": str(ev.get("message", ""))[:500]})
            return {"ok": True}
        # El juez puede tardar: se renueva el plazo del trabajo antes de llamarlo.
        queue().progress(job_id, body.lease_id, {"stage": "juez", "detail": "el juez revisa la evidencia"})
        res = await judge_and_pay(task, job, ev)
        try:
            queue().finish(job_id, body.lease_id, "done", {"result": m.public(res)})
        except LeaseError:
            # El plazo venció durante el juez: el veredicto ya quedó en la caché de la tarea, así que
            # si el trabajo se vuelve a correr responde desde la caché sin contar otro envío.
            pass
        return {"ok": True}


async def judge_and_pay(task: dict, job: dict, ev: dict) -> dict:
    """Juez, regla final, veredicto v2 y pago. Mismas reglas de plazo y reintento que `/evaluate`."""
    m = api()
    idx = job["payload"].get("milestone")
    target = hitos.target_for(task, idx)
    spec, suite = target["spec"], target["suite"]
    workspace_hash = str(ev["workspace_hash"])
    ch = workspace_hash.removeprefix("sha256:")
    video_url = job["payload"].get("video_url")

    cached = target["cache"].get(ch)
    if cached is not None:
        return {**cached, "stage": "cache"}
    if suite.get("profile") == "web":
        return await _judge_web_and_pay(task, job, ev, workspace_hash, ch, video_url)

    files: dict[str, str] = {str(k): str(v) for k, v in (ev.get("files") or {}).items()}
    tests = ev.get("tests") or {}
    outcomes = tests.get("outcomes") or []
    hygiene = ev.get("hygiene") or {}
    build = ev.get("build")
    security_problems = security_scan(files, spec["allowed_deps"]) if not hygiene.get("blockers") else []
    signals = collect_signals(load_sources(files), spec["examples"]) + output_signals(outcomes)
    grouped = _outcomes_by_criterion(outcomes)

    test_run_error = None
    ran_ok = not hygiene.get("blockers") and not (build and (build.get("exit_code") != 0 or build.get("timed_out")))
    if ran_ok and any(c["tipo"] == "test" for c in suite["criteria"]):
        if not tests:
            test_run_error = "la suite no se ejecutó"
        elif tests.get("timed_out"):
            test_run_error = "la suite superó el tiempo máximo (¿bucle infinito al importar?)"
        elif not tests.get("report_found"):
            test_run_error = "la suite no produjo reporte: " + str(tests.get("stderr_tail", ""))[-300:]

    verdict_judge = checker = judge_error = None
    usage: list[Usage] = []
    if ran_ok and not security_problems:
        checker = EvidenceChecker(spec, files, suite["files"], outcomes)
        try:
            verdict_judge = await judge(spec, suite, grouped, signals, files, m.app.state.gemini, usage)
        except LLMError as exc:
            judge_error = str(exc)[:300]

    decision = decide(suite=suite, hygiene=hygiene, build=build, security_problems=security_problems,
                      signals=signals, outcomes=grouped, test_run_error=test_run_error,
                      judge=verdict_judge, judge_error=judge_error, checker=checker)
    comparison = decision.comparison()
    reason = decision.reason()
    vh = verdict_hash_v2(task_id=task["task_id"], rules_hash=target["rules_hash"], suite_hash=suite["suite_hash"],
                         workspace_hash=workspace_hash, approved=decision.approved, stage=decision.stage,
                         criteria=decision.hash_criteria(), video_url=video_url)
    res = {
        "task_id": task["task_id"],
        "approved": decision.approved,
        "reason": reason,
        "transaction_hash": None,
        "stage": decision.stage,
        "analysis": comparison + decision.reasons,
        "comparison": comparison,
        "code_hash": ch,
        "verdict_hash": vh,
        "verdict_reason": reason,
        "security_flags": decision.security_flags,
        "video_url": video_url,
        "payment_retryable": False,
        "verdict_version": 2,
        "workspace_hash": workspace_hash,
        "suite_hash": suite["suite_hash"],
        "verification": {**decision.as_dict(), "timings_s": ev.get("timings_s"), "usage": [u.__dict__ for u in usage],
                         "sut_logs_tail": (tests.get("sut") or {}).get("logs_tail", "")[-2000:],
                         "hygiene_warnings": hygiene.get("warnings", [])},
    }
    if idx is not None:
        res["milestone"] = idx
    return await _record_and_pay(task, job, res, files, decision)


async def _record_and_pay(task: dict, job: dict, res: dict, files: dict[str, str], decision) -> dict:
    """Guarda la entrega (protegida hasta el pago), paga si se aprobó y cuenta el envío."""
    m = api()
    idx = job["payload"].get("milestone")
    target = hitos.target_for(task, idx)
    ch, video_url = res["code_hash"], res["video_url"]
    source = job["payload"]["source"]
    target["codes"][ch] = {"code": _as_code(files, source), "files": files, "source": {k: v for k, v in source.items()
                           if k != "code"}, "video_url": video_url, "code_hash": ch, "approved": decision.approved}
    target["latest_code_hash"] = ch

    counted = True
    if decision.approved:
        onchain, _now = await m.read_target_chain(task, idx)
        if not onchain or onchain["status"] != "Funded":
            await m.settle_not_funded(task, res, milestone=idx)
        else:
            left = await m.seconds_left(onchain["deadline"])
            if left is None:
                m.network_error(res)
            elif left < m.RELEASE_BUDGET_SECS:
                res["reason"] = m.REASON_NO_TIME_TO_RELEASE
                counted = False
            else:
                res["payment_retryable"] = True
                target["cache"][ch] = res
                m.store().save()
                await m.try_payment(task, res, milestone=idx)
    if counted:
        target["submissions"].append({"code_hash": ch, "stage": decision.stage, "approved": decision.approved,
                                      "at": int(time.time()), "verification": job["id"]})
    target["cache"][ch] = res
    m.store().save()
    return res


MAX_JUDGE_IMAGES = 10
MAX_SCREENSHOTS = 24


async def _store_screenshots(task_id: str, job_id: str, raw: list) -> tuple[list[dict], list[dict]]:
    """Decodifica y guarda las capturas. Devuelve (metadatos, imágenes para el juez)."""
    store = evidencia.make_store()
    metas, images = [], []
    for shot in raw[:MAX_SCREENSHOTS]:
        try:
            sid = str(shot["id"])
            data = base64.b64decode(str(shot["jpeg_b64"]), validate=True)
            key = evidencia.screenshot_key(task_id, job_id, sid)
        except (KeyError, binascii.Error, ValueError, evidencia.EvidenceError):
            continue
        if not data.startswith(b"\xff\xd8") or len(data) > 2_000_000:
            continue  # no es un JPEG (lo produce el runner confiable; aquí solo se comprueba)
        meta = {"id": sid, "page": str(shot.get("page", ""))[:100], "viewport": str(shot.get("viewport", ""))[:10],
                "label": str(shot.get("label", ""))[:120], "sha256": hashlib.sha256(data).hexdigest(), "key": key,
                "bytes": len(data)}
        try:
            await store.put(key, data)
        except evidencia.EvidenceError as exc:
            log.warning("no se pudo guardar la captura %s: %s", key, exc)
            meta["key"] = None
        metas.append(meta)
        images.append({**meta, "data": data})
    return metas, images


async def _judge_web_and_pay(task: dict, job: dict, ev: dict, workspace_hash: str, ch: str, video_url) -> dict:
    m = api()
    idx = job["payload"].get("milestone")
    target = hitos.target_for(task, idx)
    spec, suite = target["spec"], target["suite"]
    files: dict[str, str] = {str(k): str(v) for k, v in (ev.get("files") or {}).items()}
    hygiene, site, web = ev.get("hygiene"), ev.get("site"), ev.get("web")
    shots, images = await _store_screenshots(task["task_id"], job["id"], ev.get("screenshots") or [])
    dom, hidden_all = web_mod.dom_signals(web or {})
    signals = web_mod.source_signals(files) + dom

    ran = bool(hygiene) and not hygiene.get("blockers") and not (site or {}).get("error") and bool((web or {}).get("report_found"))
    verdict_judge = checker = judge_error = None
    usage: list[Usage] = []
    if ran:
        # Al juez: primero las capturas de página completa y luego las de después de interactuar.
        ordered = sorted(images, key=lambda im: (im["label"] != "página completa", int(im["id"][1:])))[:MAX_JUDGE_IMAGES]
        checker = WebEvidenceChecker(spec, files, {im["id"] for im in ordered})
        try:
            verdict_judge = await judge_web(spec, suite, web, signals, hidden_all, files, ordered,
                                            m.app.state.gemini, usage)
        except LLMError as exc:
            judge_error = str(exc)[:300]

    decision = decide_web(suite=suite, hygiene=hygiene, site=site, web=web, signals=signals,
                          judge=verdict_judge, judge_error=judge_error, checker=checker)
    comparison = decision.comparison()
    reason = decision.reason()
    vh = verdict_hash_v2(task_id=task["task_id"], rules_hash=target["rules_hash"], suite_hash=suite["suite_hash"],
                         workspace_hash=workspace_hash, approved=decision.approved, stage=decision.stage,
                         criteria=decision.hash_criteria(), video_url=video_url,
                         evidence={s["id"]: s["sha256"] for s in shots})
    res = {
        "task_id": task["task_id"],
        "approved": decision.approved,
        "reason": reason,
        "transaction_hash": None,
        "stage": decision.stage,
        "analysis": comparison + decision.reasons,
        "comparison": comparison,
        "code_hash": ch,
        "verdict_hash": vh,
        "verdict_reason": reason,
        "security_flags": decision.security_flags,
        "video_url": video_url,
        "payment_retryable": False,
        "verdict_version": 2,
        "workspace_hash": workspace_hash,
        "suite_hash": suite["suite_hash"],
        "verification": {**decision.as_dict(), "profile": "web", "timings_s": ev.get("timings_s"),
                         "usage": [u.__dict__ for u in usage], "screenshots": shots,
                         "hidden_text": hidden_all[:30], "site": site,
                         "console_errors": (web or {}).get("console", [])[:20],
                         "judge_summary": verdict_judge.summary if verdict_judge else None,
                         "hygiene_warnings": (hygiene or {}).get("warnings", [])},
    }
    if idx is not None:
        res["milestone"] = idx
    return await _record_and_pay(task, job, res, files, decision)


# --- públicas ----------------------------------------------------------------------------

@router.get("/tasks/{task_id}/suite")
async def task_suite(task_id: str, milestone: int | None = None):
    guard_enabled()
    m = api()
    task = m.get_task_or_404(task_id)
    if task.get("verification") != "execution":
        raise m.err(404, "NOT_FOUND", "Esta tarea no usa verificación por ejecución")
    idx = m.resolve_milestone_index(task, milestone)
    target = hitos.target_for(task, idx)
    await reconcile_suite(task, idx)
    if arranque.suite_waiting(target["suite"]):
        arranque.wake(m.app)
    out = {"task_id": task_id, **perfil.public_plan(target["suite"]), "retries_left": retries_left(target)}
    if idx is not None:
        out["milestone"] = idx
    return out


def retries_left(target: dict) -> int:
    return max(0, MAX_SUITE_RETRIES - target.get("suite_retries", 0))


@router.post("/tasks/{task_id}/suite/reintentar", status_code=202)
async def retry_suite(task_id: str, request: Request, milestone: int | None = None,
                      x_client_token: str | None = Header(default=None)):
    """El cliente pide preparar otra vez una suite rechazada, sin crear otra tarea.

    El `rules_hash` no depende de la suite, así que sirve también si ya depositó. Solo con la suite
    rechazada y como máximo `MAX_SUITE_RETRIES` veces; usa la misma cuota que crear una tarea.
    """
    guard_enabled()
    m = api()
    task = m.get_task_or_404(task_id)
    if task.get("verification") != "execution":
        raise m.err(404, "NOT_FOUND", "Esta tarea no usa verificación por ejecución")
    if not m.token_ok(task["client_token"], x_client_token):
        raise m.err(403, "INVALID_TOKEN", "Token de cliente inválido para esta tarea")
    idx = m.resolve_milestone_index(task, milestone)
    async with m.store().lock(task_id):
        target = hitos.target_for(task, idx)
        if target["suite"]["status"] != "rechazada":
            raise m.err(409, "SUITE_NOT_REJECTED", "Solo se puede pedir otro intento de una suite rechazada")
        if retries_left(target) <= 0:
            raise m.err(429, "TOO_MANY_SUITE_RETRIES",
                        f"Ya se usaron los {MAX_SUITE_RETRIES} intentos extra; crea otra tarea con los criterios ajustados")
        admit_suite(client_ip(request))
        start_suite(task, idx)
        target["suite_retries"] = target.get("suite_retries", 0) + 1
        m.store().save()
    arranque.wake(m.app)
    target = hitos.target_for(task, idx)
    out = {"task_id": task_id, **perfil.public_plan(target["suite"]), "retries_left": retries_left(target)}
    if idx is not None:
        out["milestone"] = idx
    return out


class CodeSource(Strict):
    kind: Literal["code"]
    code: StrictStr = Field(min_length=1)


class RepoSource(Strict):
    kind: Literal["github_public"]
    repo: StrictStr = Field(pattern=REPO_RE)
    sha: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")


class ZipSourceIn(Strict):
    kind: Literal["zip"]
    zip_b64: StrictStr


SourceIn = Annotated[Union[CodeSource, RepoSource, ZipSourceIn], Field(discriminator="kind")]


class VerifyIn(Strict):
    freelancer_address: StrictStr
    source: SourceIn
    video_url: StrictStr | None = None
    milestone: StrictInt | None = Field(default=None, ge=0)


def _in_flight(task_id: str, milestone: int | None = None) -> bool:
    return any(j["kind"] == "verify" and j["payload"].get("milestone") == milestone
               and j["status"] in ("queued", "running") for j in queue().for_task(task_id))


@router.post("/tasks/{task_id}/verificaciones", status_code=202)
async def enqueue_verification(task_id: str, body: VerifyIn, x_freelancer_token: str | None = Header(default=None)):
    guard_enabled()
    m = api()
    task = m.get_task_or_404(task_id)
    if task.get("verification") != "execution":
        raise m.err(409, "NOT_EXECUTION_TASK", "Esta tarea se evalúa con POST /evaluate")
    async with m.store().lock(task_id):
        if not task["freelancer_address"]:
            raise m.err(409, "CRITERIA_NOT_ACCEPTED", "Ningún programador ha aceptado los criterios")
        if (not m.token_ok(task["freelancer_token"], x_freelancer_token)
                or body.freelancer_address != task["freelancer_address"]):
            raise m.err(403, "INVALID_TOKEN", "Token de programador inválido para esta tarea")
        idx = m.resolve_milestone_index(task, body.milestone)
        target = hitos.target_for(task, idx)
        if target["suite"]["status"] != "lista":
            raise m.err(409, "SUITE_NOT_READY", "La suite oculta todavía no está lista")
        try:
            video_url = m.normalize_video(body.video_url)
        except ValueError as exc:
            raise m.err(400, "INVALID_REQUEST", str(exc)) from exc
        if _in_flight(task_id, idx):
            raise m.err(409, "VERIFICATION_IN_PROGRESS", "Ya hay una verificación en curso para esta tarea")
        if len(target["submissions"]) >= m.MAX_SUBMISSIONS:
            raise m.err(429, "TOO_MANY_SUBMISSIONS", f"Ya se usaron los {m.MAX_SUBMISSIONS} envíos de esta tarea")
        onchain, now = await m.read_target_chain(task, idx)
        if not onchain or onchain["status"] != "Funded":
            raise m.err(409, "TASK_NOT_FUNDED", "La tarea no está depositada en el contrato")
        if (onchain["amount"] != target["amount"] or onchain["client"] != task["client_address"]
                or onchain["rules_hash"] != target["rules_hash"]):
            raise m.err(409, "TASK_MISMATCH", "El monto, el cliente o los criterios on-chain no coinciden")
        if idx is not None and onchain.get("freelancer") and onchain["freelancer"] != task["freelancer_address"]:
            raise m.err(409, "TASK_MISMATCH", "El proyecto on-chain está fijado a otro programador")
        if idx is not None and task.get("sequential") and idx > 0 and onchain.get("previous_status") != "Released":
            raise m.err(409, "PREVIOUS_MILESTONE_NOT_RELEASED",
                        "Debes cobrar el hito anterior antes de evaluar este hito")
        if onchain["deadline"] - now < VERIFY_MIN_SECONDS:
            raise m.err(409, "DEADLINE_TOO_CLOSE",
                        f"Quedan menos de {VERIFY_MIN_SECONDS} s de plazo; ya no se puede verificar por ejecución")

        src = body.source
        if isinstance(src, CodeSource) and target["suite"].get("profile") == "web":
            raise m.err(400, "INVALID_REQUEST", "Un sitio web se entrega como ZIP o como repositorio público")
        zip_data = None
        if isinstance(src, CodeSource):
            if len(src.code.encode("utf-8")) > MAX_PASTE_BYTES:
                raise m.err(400, "INVALID_REQUEST", f"El código pegado supera {MAX_PASTE_BYTES} bytes; usa un ZIP o un repositorio")
            modules = {s["module"] for s in target["spec"]["interface"]["symbols"]}
            if len(modules) != 1:
                raise m.err(400, "INVALID_REQUEST", "La interfaz usa varios módulos: entrega un ZIP o un repositorio")
            source = {"kind": "code", "module": modules.pop(), "code": src.code}
        elif isinstance(src, RepoSource):
            source = {"kind": "github_public", "repo": src.repo, "sha": src.sha}
        else:
            try:
                data = base64.b64decode(src.zip_b64, validate=True)
            except (binascii.Error, ValueError):
                raise m.err(400, "INVALID_REQUEST", "zip_b64 no es base64 válido") from None
            if len(data) > MAX_ZIP_BYTES:
                raise m.err(400, "INVALID_REQUEST", f"El ZIP supera {MAX_ZIP_BYTES} bytes")
            zip_data = data

        # Al final de las validaciones y antes de guardar el ZIP: un rechazo anterior no gasta cuota.
        rate_limiter.consume_daily("verificacion")
        if zip_data is not None:
            source = {"kind": "zip", "source_id": queue().put_source(task_id, zip_data)}
        payload = {"spec": execution_spec(target["spec"]), "source": source, "video_url": video_url}
        if idx is not None:
            payload["milestone"] = idx
        job = queue().enqueue("verify", task_id, payload)
        target.setdefault("verifications", []).append({"job_id": job["id"], "at": int(time.time())})
        m.store().save()
        arranque.wake(m.app)
        out = {"verification_id": job["id"], "status": job["status"], "submissions_used": len(target["submissions"])}
        if idx is not None:
            out["milestone"] = idx
        return out


STAGE_LABELS = {
    "ingesta": "Obteniendo la entrega", "higiene": "Revisando archivos y dependencias",
    "dependencias": "Instalando dependencias", "tests": "Corriendo la suite oculta",
    "juez": "El juez revisa la evidencia", "suite": "Preparando la suite oculta",
}


@router.get("/verificaciones/{job_id}")
async def verification_status(job_id: str, x_freelancer_token: str | None = Header(default=None),
                              x_client_token: str | None = Header(default=None)):
    guard_enabled()
    m = api()
    job = queue().get(job_id)
    if not job or job["kind"] != "verify":
        raise m.err(404, "NOT_FOUND", "No existe esa verificación")
    task = m.get_task_or_404(job["task_id"])
    is_freelancer = m.token_ok(task.get("freelancer_token"), x_freelancer_token)
    is_client = m.token_ok(task["client_token"], x_client_token)
    if not (is_freelancer or is_client):
        raise m.err(403, "INVALID_TOKEN", "Token inválido para esta verificación")
    if job["status"] == "queued":
        arranque.wake(m.app)  # sigue en cola: la VM pudo apagarse o Google la detuvo (Spot)
    idx = job["payload"].get("milestone")
    target = hitos.target_for(task, idx)
    out = {
        "verification_id": job_id,
        "task_id": job["task_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "progress": [{**p, "label": STAGE_LABELS.get(p["stage"], p["stage"])} for p in job["progress"]],
        "submissions_used": len(target["submissions"]),
    }
    if idx is not None:
        out["milestone"] = idx
    res = (job.get("result") or {})
    if job["status"] == "done" and "result" in res:
        r = dict(res["result"])
        if is_client and not is_freelancer:
            # El cliente ve lo mismo que en /verdicts: nunca el código ni los logs de la entrega.
            r.get("verification", {}).pop("sut_logs_tail", None)
        ver = r.get("verification")
        if isinstance(ver, dict) and ver.get("screenshots"):
            # URL firmada nueva en cada consulta (15 minutos); la clave interna no sale.
            r["verification"] = {**ver, "screenshots": evidencia.public_screenshots(ver["screenshots"])}
        out["result"] = r
    elif job["status"] == "failed":
        out["error"] = res.get("error", "VERIFIER_FAILED")
        out["message"] = res.get("message") or "El verificador no pudo terminar; el envío no se contó."
    return out


DEFAULT_STUCK_SECS = 15 * 60


@router.get("/verifier/acceso")
async def verifier_access(address: str = ""):
    """¿Esta dirección puede crear tareas por ejecución? El frontend muestra la opción solo si sí."""
    guard_enabled()
    from . import client_allowed

    return {"available": bool(address) and client_allowed(address)}


@router.get("/health/verificador")
async def verifier_health():
    """Salud de la cola para un monitor externo (p. ej. un uptime check de Cloud Monitoring).

    Responde 503 si el trabajo más viejo lleva en cola más de `VERIFIER_STUCK_SECS` (15 min por
    defecto): la VM tarda 1 o 2 minutos en encender, así que eso significa que nadie está tomando
    trabajos. Solo conteos agregados: ni tareas, ni tokens, ni código.
    """
    guard_enabled()
    stats = queue().stats()
    oldest = stats["oldest_queued_at"]
    waiting = max(0, round(time.time() - oldest)) if oldest else 0
    stuck_after = _limit("VERIFIER_STUCK_SECS") or DEFAULT_STUCK_SECS
    if oldest:
        arranque.wake(api().app)  # hay trabajo esperando: que la VM esté encendida
    ok = waiting < stuck_after
    return JSONResponse({"ok": ok, "queued": stats["queued"], "running": stats["running"],
                         "oldest_queued_secs": waiting, "stuck_after_secs": stuck_after},
                        status_code=200 if ok else 503)


@router.get("/evidencia/{key:path}")
async def evidence_file(key: str, exp: int, sig: str):
    guard_enabled()
    try:
        ok = evidencia.verify(key, exp, sig)
    except evidencia.EvidenceError:
        ok = False
    if not ok:
        raise api().err(403, "INVALID_TOKEN", "El enlace de la captura no es válido o ya venció")
    try:
        data = await evidencia.make_store().get(key)
    except evidencia.EvidenceError:
        raise api().err(502, "EVIDENCE_UNAVAILABLE", "No se pudo leer la captura") from None
    if data is None:
        raise api().err(404, "NOT_FOUND", "No existe esa captura")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})
