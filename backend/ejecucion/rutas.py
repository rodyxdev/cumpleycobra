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
"""

from __future__ import annotations

import base64
import binascii
import hmac
import re
import time
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from verifier.contract import ExecutionSpec

from . import MAX_PASTE_BYTES, MAX_ZIP_BYTES, VERIFY_MIN_SECONDS, enabled, queue_token
from . import suite as suite_mod
from .cola import LeaseError
from .juez import EvidenceChecker, judge
from .regla import decide
from .seguridad import security_scan
from .senales import collect_signals, load_sources, output_signals
from ..hashing import verdict_hash_v2
from ..llm import LLMError, Usage

router = APIRouter()

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


class ValidationIn(LeaseIn):
    empty: RunIn
    stub: RunIn


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
    return ExecutionSpec(profile="script", interface=spec["interface"],
                         allowed_dependencies=spec["allowed_deps"]).model_dump(mode="json")


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
        # Los tests se leen al reclamar: siempre la suite vigente de la tarea.
        payload = {**payload, "tests": dict(task["suite"]["files"])}
    return {"id": job["id"], "kind": job["kind"], "lease_id": job["lease_id"], "payload": payload}


@router.post("/verifier/jobs/{job_id}/progress")
async def progress(job_id: str, body: ProgressIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    try:
        queue().progress(job_id, body.lease_id, {"stage": body.stage, "detail": body.detail})
    except LeaseError:
        raise api().err(409, "LEASE_INVALID", "El trabajo no está asignado a este verificador") from None
    return {"ok": True}


async def _advance_suite(job_id: str, lease_id: str, task: dict) -> dict:
    """Genera rondas hasta tener algo que validar o terminar. Quien llama tiene el candado de la tarea."""
    m = api()
    suite = task["suite"]
    while True:
        queue().progress(job_id, lease_id, {"stage": "suite", "detail": f"generando la ronda {suite['round'] + 1}"})
        try:
            await suite_mod.generate_round(task["spec"], suite, m.app.state.gemini)
        except LLMError as exc:
            suite["status"] = "rechazada"
            suite["error"] = str(exc)[:300]
            m.store().save()
            queue().finish(job_id, lease_id, "failed", {"error": suite["error"]})
            return {"next": "done"}
        to_check = {c["index"] for c in suite_mod.pending(suite)} & {
            suite_mod.criterion_index(f) for f in suite["files"]}
        if to_check:
            m.store().save()
            return {"next": "validate", "round": suite["round"], "tests": dict(suite["files"])}
        # Nada nuevo que validar: todo era lectura, o la ronda solo dejó problemas estáticos.
        if suite_mod.pending(suite) and suite["round"] <= suite_mod.MAX_REGENERATIONS:
            suite["status"] = "pendiente"
            continue
        suite_mod.finalize(suite)
        m.store().save()
        queue().finish(job_id, lease_id, "done", suite_mod.public_plan(suite))
        return {"next": "done"}


@router.post("/verifier/jobs/{job_id}/suite/generate")
async def suite_generate(job_id: str, body: LeaseIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    m = api()
    task = m.get_task_or_404(job["task_id"])
    async with m.store().lock(task["task_id"]):
        return await _advance_suite(job_id, body.lease_id, task)


@router.post("/verifier/jobs/{job_id}/suite/validation")
async def suite_validation(job_id: str, body: ValidationIn, authorization: str | None = Header(default=None)):
    guard_worker(authorization)
    job = leased(job_id, body.lease_id)
    m = api()
    task = m.get_task_or_404(job["task_id"])
    async with m.store().lock(task["task_id"]):
        again = suite_mod.apply_validation(task["suite"], body.empty.model_dump(), body.stub.model_dump())
        m.store().save()
        if again:
            return await _advance_suite(job_id, body.lease_id, task)
    queue().finish(job_id, body.lease_id, "done", suite_mod.public_plan(task["suite"]))
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
    leased(job_id, body.lease_id)
    queue().finish(job_id, body.lease_id, "failed", {"error": body.message})
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
    spec, suite = task["spec"], task["suite"]
    workspace_hash = str(ev["workspace_hash"])
    ch = workspace_hash.removeprefix("sha256:")
    video_url = job["payload"].get("video_url")

    cached = task["cache"].get(ch)
    if cached is not None:
        return {**cached, "stage": "cache"}

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
    vh = verdict_hash_v2(task_id=task["task_id"], rules_hash=task["rules_hash"], suite_hash=suite["suite_hash"],
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
    source = job["payload"]["source"]
    task["codes"][ch] = {"code": _as_code(files, source), "files": files, "source": {k: v for k, v in source.items()
                         if k != "code"}, "video_url": video_url, "code_hash": ch, "approved": decision.approved}
    task["latest_code_hash"] = ch

    counted = True
    if decision.approved:
        onchain, _now = await m.read_chain(task["task_id"])
        if not onchain or onchain["status"] != "Funded":
            await m.settle_not_funded(task, res)
        else:
            left = await m.seconds_left(onchain["deadline"])
            if left is None:
                m.network_error(res)
            elif left < m.RELEASE_BUDGET_SECS:
                res["reason"] = m.REASON_NO_TIME_TO_RELEASE
                counted = False
            else:
                res["payment_retryable"] = True
                task["cache"][ch] = res
                m.store().save()
                await m.try_payment(task, res)
    if counted:
        task["submissions"].append({"code_hash": ch, "stage": decision.stage, "approved": decision.approved,
                                    "at": int(time.time()), "verification": job["id"]})
    task["cache"][ch] = res
    m.store().save()
    return res


# --- públicas ----------------------------------------------------------------------------

@router.get("/tasks/{task_id}/suite")
async def task_suite(task_id: str):
    guard_enabled()
    task = api().get_task_or_404(task_id)
    if task.get("verification") != "execution":
        raise api().err(404, "NOT_FOUND", "Esta tarea no usa verificación por ejecución")
    return {"task_id": task_id, **suite_mod.public_plan(task["suite"])}


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


def _in_flight(task_id: str) -> bool:
    return any(j["kind"] == "verify" and j["status"] in ("queued", "running") for j in queue().for_task(task_id))


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
        if task["suite"]["status"] != "lista":
            raise m.err(409, "SUITE_NOT_READY", "La suite oculta todavía no está lista")
        try:
            video_url = m.normalize_video(body.video_url)
        except ValueError as exc:
            raise m.err(400, "INVALID_REQUEST", str(exc)) from exc
        if _in_flight(task_id):
            raise m.err(409, "VERIFICATION_IN_PROGRESS", "Ya hay una verificación en curso para esta tarea")
        if len(task["submissions"]) >= m.MAX_SUBMISSIONS:
            raise m.err(429, "TOO_MANY_SUBMISSIONS", f"Ya se usaron los {m.MAX_SUBMISSIONS} envíos de esta tarea")
        onchain, now = await m.read_chain(task_id)
        if not onchain or onchain["status"] != "Funded":
            raise m.err(409, "TASK_NOT_FUNDED", "La tarea no está depositada en el contrato")
        if (onchain["amount"] != task["amount"] or onchain["client"] != task["client_address"]
                or onchain["rules_hash"] != task["rules_hash"]):
            raise m.err(409, "TASK_MISMATCH", "El monto, el cliente o los criterios on-chain no coinciden")
        if onchain["deadline"] - now < VERIFY_MIN_SECONDS:
            raise m.err(409, "DEADLINE_TOO_CLOSE",
                        f"Quedan menos de {VERIFY_MIN_SECONDS} s de plazo; ya no se puede verificar por ejecución")

        src = body.source
        if isinstance(src, CodeSource):
            if len(src.code.encode("utf-8")) > MAX_PASTE_BYTES:
                raise m.err(400, "INVALID_REQUEST", f"El código pegado supera {MAX_PASTE_BYTES} bytes; usa un ZIP o un repositorio")
            modules = {s["module"] for s in task["spec"]["interface"]["symbols"]}
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
            source = {"kind": "zip", "source_id": queue().put_source(task_id, data)}

        job = queue().enqueue("verify", task_id, {"spec": execution_spec(task["spec"]), "source": source,
                                                  "video_url": video_url})
        task.setdefault("verifications", []).append({"job_id": job["id"], "at": int(time.time())})
        m.store().save()
        return {"verification_id": job["id"], "status": job["status"], "submissions_used": len(task["submissions"])}


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
    out = {
        "verification_id": job_id,
        "task_id": job["task_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "progress": [{**p, "label": STAGE_LABELS.get(p["stage"], p["stage"])} for p in job["progress"]],
        "submissions_used": len(task["submissions"]),
    }
    res = (job.get("result") or {})
    if job["status"] == "done" and "result" in res:
        r = dict(res["result"])
        if is_client and not is_freelancer:
            # El cliente ve lo mismo que en /verdicts: nunca el código ni los logs de la entrega.
            r.get("verification", {}).pop("sut_logs_tail", None)
        out["result"] = r
    elif job["status"] == "failed":
        out["error"] = res.get("error", "VERIFIER_FAILED")
        out["message"] = res.get("message") or "El verificador no pudo terminar; el envío no se contó."
    return out
