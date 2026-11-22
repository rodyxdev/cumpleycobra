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

Apagado por inactividad: con `VERIFIER_IDLE_SHUTDOWN_SECS` (en la VM, 900), si pasa ese tiempo sin
trabajos el trabajador deja de pedir trabajo y apaga la máquina (`systemctl poweroff`; en GCE la
instancia queda detenida y deja de cobrar CPU). Como deja de pedir antes de apagar, nunca corta un
trabajo a medias. La API la vuelve a encender cuando hay trabajo (`backend/ejecucion/arranque.py`).

Uso:
    VERIFIER_API_URL=https://... VERIFIER_QUEUE_TOKEN=... python -m verifier.worker
    python -m verifier.worker --once     # un solo trabajo (pruebas)
"""

from __future__ import annotations

import argparse
import base64
import logging
import re
import os
import subprocess
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
from verifier.web import prepare_site, run_web_checks, static_site
from verifier.web.hygiene import check_web_hygiene

log = logging.getLogger("cumpleycobra.verifier")

TEXT_SUFFIXES = {".py", ".txt", ".md", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml"}
WEB_TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
                     ".svg", ".json", ".md", ".txt"}
SCREENSHOT_MAX_BYTES = 1_500_000      # por captura (JPEG)
SCREENSHOTS_MAX_BYTES = 12_000_000    # todas juntas, en la evidencia que viaja a la API
EMPTY_SITE = '<!doctype html><html><head><meta charset="utf-8"><title></title></head><body></body></html>\n'
REFERENCE_FILE_RE = re.compile(r"^(?:[a-z0-9_-]+/)*[a-z0-9_-]+\.(?:html|css|js)$")
FILES_CHAR_LIMIT = 200_000      # lo que viaja a la API para el juez y para la entrega al cliente
LOGS_TAIL = 3_000
IDLE_SLEEP_SECS = 3
POWER_OFF = ["systemctl", "poweroff"]


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


def text_files(root: Path, suffixes: set[str] = TEXT_SUFFIXES) -> tuple[dict[str, str], bool]:
    """Archivos de texto de la entrega (para el juez). Devuelve (archivos, truncado)."""
    files, used, truncated = {}, 0, False
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in suffixes:
            continue
        if "node_modules" in path.relative_to(root).parts or path.name == "package-lock.json":
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

def web_validation_summary(run) -> dict:
    """Lo que necesita la API para validar los chequeos: resultados, sin capturas ni texto de páginas."""
    full = run.summary()
    return {k: full[k] for k in ("report_found", "exit_code", "timed_out", "duration_s", "stderr_tail", "checks", "errors")}


def _open_dirs(root: Path) -> None:
    # mkdtemp crea 0700 y los contenedores corren como nobody.
    for d in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
        d.chmod(0o755)


def write_reference_site(dest: Path, files: dict[str, str]) -> None:
    """Sitio de referencia que escribió el modelo: solo .html/.css/.js con rutas simples."""
    dest.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        if not REFERENCE_FILE_RE.fullmatch(rel):
            raise ValueError(f"ruta no permitida en el sitio de referencia: {rel!r}")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _open_dirs(dest)


def empty_site(dest: Path, pages: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(EMPTY_SITE, encoding="utf-8")
    for page in pages:
        if page.strip("/"):
            page_dir = dest / page.strip("/")
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "index.html").write_text(EMPTY_SITE, encoding="utf-8")
    _open_dirs(dest)


def run_web_suite_step(step: dict) -> dict:
    """Valida una ronda de chequeos web contra un sitio vacío y contra el de referencia."""
    with tempfile.TemporaryDirectory(prefix="cc-websuite-") as tmp:
        tmp = Path(tmp)
        tmp.chmod(0o755)
        empty = tmp / "vacia"
        empty_site(empty, step["pages"])
        body = {"web_empty": web_validation_summary(
            run_web_checks(static_site(empty), step["pages"], step["checks"], tmp / "out-vacia"))}
        if step.get("reference_site"):
            ref = tmp / "referencia"
            try:
                write_reference_site(ref, step["reference_site"])
            except ValueError as exc:
                log.warning("sitio de referencia descartado: %s", exc)
                return body
            body["web_reference"] = web_validation_summary(
                run_web_checks(static_site(ref), step["pages"], step["checks"], tmp / "out-ref"))
        return body


def run_suite_job(job: Job) -> None:
    spec = ExecutionSpec.model_validate(job.payload["spec"])
    step = job.send("suite/generate", {})
    if spec.profile == "web":
        while step and step.get("next") == "validate":
            job.progress("suite", f"validando la ronda {step.get('round')} en un navegador")
            step = job.send("suite/validation", run_web_suite_step(step))
        return
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


def screenshot_evidence(run, out: Path) -> tuple[list[dict], list[str]]:
    """Capturas en base64 para la API (la VM no tiene credenciales: la API las guarda)."""
    shots, skipped, used = [], [], 0
    for shot in (run.results or {}).get("screenshots", []):
        path = out / str(shot.get("file", ""))
        if not re.fullmatch(r"S[0-9]{1,3}", str(shot.get("id", ""))) or path.name != f"{shot['id']}.jpg" or not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > SCREENSHOT_MAX_BYTES or used + len(data) > SCREENSHOTS_MAX_BYTES:
            skipped.append(shot["id"])
            continue
        used += len(data)
        shots.append({**shot, "jpeg_b64": base64.b64encode(data).decode("ascii")})
    return shots, skipped


def run_web_verify(job: Job, spec: ExecutionSpec, ws, work: Path, evidence: dict, lap, t: float) -> None:
    hygiene = check_web_hygiene(ws.path, spec.allowed_dependencies)
    evidence["hygiene"] = asdict(hygiene)
    t = lap("higiene", t)
    if not hygiene.ok:
        return
    if (ws.path / "package.json").exists():
        job.progress("dependencias", "npm ci y npm run build")
    site = prepare_site(ws.path)
    try:
        evidence["site"] = site.summary()
        t = lap("dependencias", t)
        if site.ok:
            job.progress("navegador", "revisando el sitio en un navegador a 1440 y 390 px")
            out = work / "web-out"
            run = run_web_checks(site, spec.web.pages, job.payload["checks"], out)
            evidence["web"] = run.summary()
            evidence["screenshots"], evidence["screenshots_skipped"] = screenshot_evidence(run, out)
            lap("navegador", t)
    finally:
        site.remove()


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
            if spec.profile == "web":
                files, truncated = text_files(ws.path, WEB_TEXT_SUFFIXES)
                evidence = {"profile": "web", "workspace_hash": ws.content_hash, "source": ws.source,
                            "size_bytes": ws.size_bytes, "files": files, "files_truncated": truncated,
                            "hygiene": None, "site": None, "web": None, "screenshots": []}
                run_web_verify(job, spec, ws, work, evidence, lap, t)
                timings["total"] = round(time.monotonic() - t0, 3)
                evidence["timings_s"] = timings
                job.progress("juez", "evidencia enviada; el juez la revisa en la API")
                job.send("result", {"evidence": evidence})
                return
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


def idle_shutdown_secs() -> float | None:
    raw = (os.environ.get("VERIFIER_IDLE_SHUTDOWN_SECS") or "").strip()
    if raw in ("", "0"):
        return None
    secs = float(raw)
    if secs < 60:
        raise ValueError("VERIFIER_IDLE_SHUTDOWN_SECS debe ser de al menos 60 s")
    return secs


def power_off() -> bool:
    """Apaga la máquina. Devuelve False si no se pudo (el trabajador sigue atendiendo)."""
    try:
        return subprocess.run(POWER_OFF, check=False, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("no se pudo apagar la máquina (%s)", type(exc).__name__)
        return False


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
    idle_limit = idle_shutdown_secs()
    last_job = time.monotonic()   # el arranque cuenta como actividad
    while True:
        if idle_limit is not None and not args.once and time.monotonic() - last_job >= idle_limit:
            log.info("%d s sin trabajos: se apaga la máquina", int(idle_limit))
            if power_off():
                return 0
            last_job = time.monotonic()  # no se pudo: sigue atendiendo y lo intenta más tarde
        try:
            raw = api.post("/verifier/claim", {})
        except httpx.HTTPError as exc:
            log.warning("no se pudo pedir trabajo (%s)", type(exc).__name__)
            raw = None
            if args.once:
                return 1
        if raw:
            log.info("trabajo %s (%s)", raw["id"], raw["kind"])
            last_job = time.monotonic()
            try:
                handle(Job(api, raw))
            except httpx.HTTPError as exc:
                log.error("la API rechazó el trabajo %s (%s)", raw["id"], exc)
            last_job = time.monotonic()  # el plazo de inactividad cuenta desde que terminó
        if args.once:
            return 0
        if not raw:
            time.sleep(IDLE_SLEEP_SECS)


if __name__ == "__main__":
    sys.exit(main())
