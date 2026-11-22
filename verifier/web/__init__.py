"""Perfil web del verificador (fase 3, portado de v2 sin video).

La entrega se sirve en un contenedor (servidor estático nuestro) dentro de una red interna, y un
segundo contenedor CONFIABLE con Playwright la visita a 1440 px y 390 px: corre los chequeos
deterministas del catálogo (`verifier.contract.WebCheck`), toma capturas JPEG y recoge el texto
visible, el texto oculto y el desborde horizontal. La entrega nunca ve los chequeos.

Lo visual (¿se parece a lo pedido?, ¿se lee bien?) lo juzga el modelo en la API con las capturas.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from verifier.config import get_settings
from verifier.sandbox.runner import (
    InternalNetwork,
    Mount,
    SandboxLimits,
    SandboxResult,
    SandboxUnavailable,
    _docker,
    ensure_image,
    run_in_sandbox,
)
from verifier.web.serve import SiteBuild, prepare_site, serve_site, static_site

RUNNER = Path(__file__).parent / "runtime" / "web_runner.py"
RUNNER_IMAGE_DIR = Path(__file__).parent / "runner_image"
EVIDENCE_LIMIT_BYTES = 64 * 1024 * 1024
MAX_SCREENSHOTS = 24

__all__ = ["WebRun", "run_web_checks", "prepare_site", "static_site", "SiteBuild", "playwright_image"]


@dataclass
class WebRun:
    sandbox: SandboxResult
    results: dict | None
    evidence_dir: Path
    server_logs: str
    server_state: dict

    def summary(self) -> dict:
        r = self.results or {}
        return {
            "report_found": self.results is not None,
            "exit_code": self.sandbox.exit_code,
            "timed_out": self.sandbox.timed_out,
            "duration_s": self.sandbox.duration_s,
            "stderr_tail": self.sandbox.stderr[-1500:],
            "checks": r.get("checks", {}),
            "pages": r.get("pages", {}),
            "console": r.get("console", [])[:20],
            "errors": r.get("errors", []),
            "screenshots": r.get("screenshots", [])[:MAX_SCREENSHOTS],
            "server": {"state": self.server_state, "logs_tail": self.server_logs[-2000:]},
        }


def playwright_image() -> str:
    configured = get_settings().web_runner_image
    if configured:
        ensure_image(configured)
        return configured
    digest = hashlib.sha256((RUNNER_IMAGE_DIR / "Dockerfile").read_bytes()).hexdigest()[:12]
    tag = f"cumpleycobra-web-runner:{digest}"
    if _docker(["image", "inspect", tag]).returncode != 0:
        built = _docker(["build", "--tag", tag, str(RUNNER_IMAGE_DIR)], timeout_s=1800)
        if built.returncode != 0:
            raise SandboxUnavailable(f"no se pudo construir {tag}: {built.stderr.strip()[-500:]}")
    return tag


def run_web_checks(site: SiteBuild, pages: list[str], checks: list[dict], evidence_dir: Path) -> WebRun:
    """Sirve `site` y corre el runner confiable. `checks` = [{"id", "kind", "page", "args"}]."""
    s = get_settings()
    image = playwright_image()
    base = SandboxLimits.from_settings()
    limits = replace(base, memory="2g", pids=1024, timeout_s=s.web_timeout_s, cpus=max(base.cpus, 2.0),
                     out_tmpfs_bytes=EVIDENCE_LIMIT_BYTES)
    with tempfile.TemporaryDirectory(prefix="cc-web-") as tmp:
        tmp = Path(tmp)
        tmp.chmod(0o755)
        (tmp / "rt").mkdir(mode=0o755)
        shutil.copy2(RUNNER, tmp / "rt" / "web_runner.py")
        (tmp / "spec").mkdir(mode=0o755)
        network = InternalNetwork()
        server = None
        try:
            server, base_url = serve_site(site, network.name)
            spec = {"base_url": base_url, "pages": pages, "checks": checks}
            (tmp / "spec" / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            result = run_in_sandbox(
                None, "python3 /cc/web_runner.py /spec/spec.json /out", evidence_dir,
                image=image, limits=limits, network=network.name,
                mounts=(Mount(str(tmp / "rt"), "/cc"), Mount(str(tmp / "spec"), "/spec")),
                env={"HOME": "/tmp", "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright"},
                extra=["--shm-size", "512m"], tmp_size="1g",
            )
            report = evidence_dir / "results.json"
            results = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
            return WebRun(result, results, evidence_dir, server.logs(), server.state())
        finally:
            if server is not None:
                server.remove()
            network.remove()
