"""Trabajador del verificador: corre en la VM sin credenciales (fase 3).

Ciclo: pide un trabajo a la API (`POST /verifier/claim`), lo ejecuta en contenedores aislados e
informa avance y evidencia. Nunca llama al modelo, nunca decide un veredicto y nunca firma: lo
único que tiene es `VERIFIER_QUEUE_TOKEN`, que solo sirve para la cola.

Trabajos:
- `suite`: la API genera tests candidatos; aquí se corren contra una entrega vacía y contra un
  stub, y se devuelven los resultados. La API decide si acepta o regenera.
- `verify`: ingesta (código pegado, ZIP o repo público con SHA), higiene, build de dependencias,
  suite oculta en caja negra. Se devuelven los resultados de los tests, los logs de la entrega y
  los archivos de texto de la entrega (para el juez, que corre en la API).

Uso:
    VERIFIER_API_URL=https://... VERIFIER_QUEUE_TOKEN=... python -m verifier.worker
    python -m verifier.worker --once     # un solo trabajo (pruebas)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from verifier.blackbox import run_blackbox
from verifier.config import get_settings
from verifier.contract import ExecutionSpec
from verifier.ingest import GitHubPublicSource, IngestError, ZipSource, fetch_submission, hash_workspace, rmtree_force
from verifier.sandbox import DepsVolume, SandboxUnavailable, build_dependencies, ensure_runner_image
from verifier.verification.hygiene import check_hygiene
from verifier.verification.stub import build_stub
from verifier.verification.suite_files import write_suite_dir

log = logging.getLogger("cumpleycobra.verifier")

TEXT_SUFFIXES = {".py", ".txt", ".md", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml"}
FILES_CHAR_LIMIT = 200_000      # lo que viaja a la API para el juez y para la entrega al cliente
LOGS_TAIL = 3_000
IDLE_SLEEP_SECS = 3


class Api:
    """Cliente de la cola. El token nunca se imprime."""

    def __init__(self, base_url: str, token: str, timeout: float = 300):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout,
                                 headers={"Authorization": f"Bearer {token}"})

    def post(self, path: str, body: dict) -> dict | None:
        resp = self.http.post(path, json=body)
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_bytes(self, path: str, params: dict) -> bytes:
        resp = self.http.get(path, params=params)
        resp.raise_for_status()
        return resp.content


class Job:
    def __init__(self, api: Api, raw: dict):
        self.api, self.id, self.kind = api, raw["id"], raw["kind"]
        self.lease_id, self.payload = raw["lease_id"], raw["payload"]

    def progress(self, stage: str, detail: str = "") -> None:
        try:
            self.api.post(f"/verifier/jobs/{self.id}/progress", {"lease_id": self.lease_id, "stage": stage, "detail": detail})
        except httpx.HTTPError as exc:  # el avance es informativo: no detiene el trabajo
            log.warning("no se pudo informar avance (%s)", type(exc).__name__)

    def send(self, action: str, body: dict) -> dict | None:
        return self.api.post(f"/verifier/jobs/{self.id}/{action}", {"lease_id": self.lease_id, **body})


# --- utilidades ---------------------------------------------------------------------------

def outcome_dicts(outcomes) -> list[dict]:
    return [asdict(o) for o in outcomes]


def run_summary(run) -> dict:
    return {
        "report_found": run.report_found,
        "outcomes": outcome_dicts(run.outcomes),
        "timed_out": run.sandbox.timed_out,
        "exit_code": run.sandbox.exit_code,
        "duration_s": run.sandbox.duration_s,
        "stderr_tail": run.sandbox.stderr[-1500:],
        "sut": {"state": run.sut_state, "logs_tail": run.sut_logs[-LOGS_TAIL:]},
    }


def sandbox_summary(r) -> dict | None:
    if r is None:
        return None
    return {"exit_code": r.exit_code, "duration_s": r.duration_s, "timed_out": r.timed_out,
            "oom_killed": r.oom_killed, "stdout_tail": r.stdout[-1500:], "stderr_tail": r.stderr[-1500:]}


def text_files(root: Path) -> tuple[dict[str, str], bool]:
    """Archivos de texto de la entrega (para el juez). Devuelve (archivos, truncado)."""
    files, used, truncated = {}, 0, False
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if used + len(text) > FILES_CHAR_LIMIT:
            truncated = True
            continue
        used += len(text)
        files[rel] = text
    return files, truncated


def write_pasted(dest: Path, module: str, code: str) -> None:
    parts = module.split(".")
    pkg = dest
    for part in parts[:-1]:
        pkg = pkg / part
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").touch()
    (pkg / f"{parts[-1]}.py").write_bytes(code.encode("utf-8"))


# --- trabajos -----------------------------------------------------------------------------

def run_suite_job(job: Job) -> None:
    spec = ExecutionSpec.model_validate(job.payload["spec"])
    step = job.send("suite/generate", {})
    while step and step.get("next") == "validate":
        job.progress("suite", f"validando la ronda {step.get('round')}")
        with tempfile.TemporaryDirectory(prefix="cc-suite-") as tmp:
            tmp = Path(tmp)
            empty, stub, suite = tmp / "empty", tmp / "stub", tmp / "suite"
            empty.mkdir()
            stub.mkdir()
            build_stub(spec.interface, stub)
            write_suite_dir(suite, step["tests"])
            empty_run = run_blackbox(empty, suite, spec)
            stub_run = run_blackbox(stub, suite, spec)
            body = {"empty": run_summary(empty_run), "stub": run_summary(stub_run)}
            if step.get("reference"):
                # Implementación de referencia (la escribió el modelo): corre igual de aislada.
                ref = tmp / "referencia"
                ref.mkdir()
                for m in step["reference"]:
                    write_pasted(ref, m["module"], m["code"])
                body["reference"] = run_summary(run_blackbox(ref, suite, spec))
        step = job.send("suite/validation", body)


def _ingest(job: Job, spec: ExecutionSpec, source: dict, work: Path):
    kind = source["kind"]
    if kind == "code":
        dest = work / "pasted"
        dest.mkdir()
        write_pasted(dest, source["module"], source["code"])
        from verifier.ingest import Workspace

        return Workspace(path=dest, content_hash=hash_workspace(dest), source={"kind": "code"})
    if kind == "zip":
        data = job.api.get_bytes(f"/verifier/jobs/{job.id}/source", {"lease_id": job.lease_id})
        zip_path = work / "entrega.zip"
        zip_path.write_bytes(data)
        return fetch_submission(ZipSource(path=zip_path), dest_root=work / "ws")
    if kind == "github_public":
        return fetch_submission(GitHubPublicSource(repo=source["repo"], sha=source["sha"]), dest_root=work / "ws")
    raise IngestError(f"fuente desconocida: {kind!r}")


def run_verify_job(job: Job) -> None:
    spec = ExecutionSpec.model_validate(job.payload["spec"])
    timings: dict[str, float] = {}
    t0 = time.monotonic()

    def lap(name: str, since: float) -> float:
        now = time.monotonic()
        timings[name] = round(now - since, 3)
        return now

    with tempfile.TemporaryDirectory(prefix="cc-verify-") as tmp:
        work = Path(tmp)
        job.progress("ingesta", "obteniendo la entrega")
        try:
            ws = _ingest(job, spec, job.payload["source"], work)
        except IngestError as exc:
            job.send("result", {"evidence": {"error": "ingest", "message": str(exc)[:500]}})
            return
        t = lap("ingesta", t0)
        try:
            job.progress("higiene", "revisando archivos y dependencias")
            hygiene = check_hygiene(ws.path, spec)
            files, truncated = text_files(ws.path)
            evidence = {"workspace_hash": ws.content_hash, "source": ws.source, "size_bytes": ws.size_bytes,
                        "hygiene": asdict(hygiene), "files": files, "files_truncated": truncated,
                        "build": None, "tests": None}
            t = lap("higiene", t)
            if hygiene.ok:
                image = ensure_runner_image()
                volume = DepsVolume(image) if hygiene.requirements else None
                try:
                    build = None
                    if volume:
                        job.progress("dependencias", ", ".join(hygiene.requirements)[:200])
                        build = build_dependencies(hygiene.requirements, volume, image)
                        evidence["build"] = sandbox_summary(build)
                        t = lap("dependencias", t)
                    if build is None or build.exit_code == 0:
                        job.progress("tests", "corriendo la suite oculta")
                        suite_dir = work / "suite"
                        write_suite_dir(suite_dir, job.payload["tests"])
                        run = run_blackbox(ws.path, suite_dir, spec, deps_mount=volume.mount() if volume else None)
                        evidence["tests"] = run_summary(run)
                        t = lap("tests", t)
                finally:
                    if volume:
                        volume.remove()
            timings["total"] = round(time.monotonic() - t0, 3)
            evidence["timings_s"] = timings
            job.progress("juez", "evidencia enviada; el juez la revisa en la API")
            job.send("result", {"evidence": evidence})
        finally:
            rmtree_force(ws.path)


def handle(job: Job) -> None:
    try:
        if job.kind == "suite":
            run_suite_job(job)
        elif job.kind == "verify":
            run_verify_job(job)
        else:
            job.send("fail", {"message": f"clase de trabajo desconocida: {job.kind}"})
    except SandboxUnavailable as exc:
        log.error("sandbox no disponible: %s", exc)
        job.send("fail", {"message": f"el verificador no pudo ejecutar la entrega: {str(exc)[:300]}"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trabajador del verificador de Cumple&Cobra")
    parser.add_argument("--once", action="store_true", help="atiende un solo trabajo y sale")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base, token = os.environ.get("VERIFIER_API_URL"), os.environ.get("VERIFIER_QUEUE_TOKEN")
    if not base or not token:
        print("Faltan VERIFIER_API_URL o VERIFIER_QUEUE_TOKEN", file=sys.stderr)
        return 2
    get_settings().work_dir.mkdir(parents=True, exist_ok=True)
    api = Api(base, token)
    while True:
        try:
            raw = api.post("/verifier/claim", {})
        except httpx.HTTPError as exc:
            log.warning("no se pudo pedir trabajo (%s)", type(exc).__name__)
            raw = None
            if args.once:
                return 1
        if raw:
            log.info("trabajo %s (%s)", raw["id"], raw["kind"])
            try:
                handle(Job(api, raw))
            except httpx.HTTPError as exc:
                log.error("la API rechazó el trabajo %s (%s)", raw["id"], exc)
        if args.once:
            return 0
        if not raw:
            time.sleep(IDLE_SLEEP_SECS)


if __name__ == "__main__":
    sys.exit(main())
