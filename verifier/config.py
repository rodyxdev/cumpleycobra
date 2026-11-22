"""Configuración del verificador, leída de variables de entorno.

El verificador no tiene secretos: no lee `.env`, ni credenciales del modelo, de Google Cloud o
del árbitro. Lo único sensible que recibe en la VM es el token de la cola (`worker.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # Ingesta
    work_dir: Path
    zip_max_upload_bytes: int
    zip_max_uncompressed_bytes: int
    zip_max_files: int
    git_timeout_s: float
    workspace_max_bytes: int
    # Sandbox
    sandbox_image: str
    sandbox_cpus: float
    sandbox_memory: str
    sandbox_pids: int
    sandbox_timeout_s: float
    sandbox_output_limit: int
    sandbox_out_bytes: int
    # Runtime de Docker para todo contenedor con código ajeno: "runsc" (gVisor) en la VM.
    # Vacío = el runtime por defecto (runc), aceptable solo en una laptop de desarrollo.
    sandbox_runtime: str | None
    build_timeout_s: float
    build_memory: str
    # Red del paso BUILD. "bridge" (salida libre) solo en desarrollo; en la VM, una red interna
    # de Docker cuya única salida es el proxy con lista blanca (`build_proxy`).
    build_network: str
    build_proxy: str | None
    # Contenedor del proxy: si está, su IP en `build_network` se resuelve en cada build (bajo gVisor
    # el alias de red no resuelve) y reemplaza al host de `build_proxy`.
    build_proxy_container: str | None
    runner_image: str | None
    # Perfil web: imagen de Playwright (en la VM, construida por startup.sh), imagen de Node para
    # el build y tiempos máximos de `npm ci` (con red, por el proxy) y del navegador.
    web_runner_image: str | None
    node_image: str
    npm_install_timeout_s: float
    web_timeout_s: float
    # Verificación
    hidden_test_timeout_s: int
    call_timeout_s: float
    blackbox_suite_timeout_s: float


def get_settings() -> Settings:
    work_dir = Path(os.getenv("VERIFIER_WORK_DIR", str(REPO_ROOT / ".data" / "verifier")))
    return Settings(
        work_dir=work_dir,
        zip_max_upload_bytes=_int("ZIP_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
        zip_max_uncompressed_bytes=_int("ZIP_MAX_UNCOMPRESSED_BYTES", 100 * 1024 * 1024),
        zip_max_files=_int("ZIP_MAX_FILES", 5_000),
        git_timeout_s=_float("GIT_TIMEOUT_S", 120.0),
        workspace_max_bytes=_int("WORKSPACE_MAX_BYTES", 200 * 1024 * 1024),
        sandbox_image=os.getenv("SANDBOX_IMAGE", "python:3.12-slim"),
        sandbox_cpus=_float("SANDBOX_CPUS", 1.0),
        sandbox_memory=os.getenv("SANDBOX_MEMORY", "512m"),
        sandbox_pids=_int("SANDBOX_PIDS", 256),
        sandbox_timeout_s=_float("SANDBOX_TIMEOUT_S", 60.0),
        sandbox_output_limit=_int("SANDBOX_OUTPUT_LIMIT", 64 * 1024),
        sandbox_out_bytes=_int("SANDBOX_OUT_BYTES", 16 * 1024 * 1024),
        sandbox_runtime=os.getenv("SANDBOX_RUNTIME") or None,
        build_timeout_s=_float("BUILD_TIMEOUT_S", 180.0),
        build_memory=os.getenv("BUILD_MEMORY", "1g"),
        build_network=os.getenv("BUILD_NETWORK") or "bridge",
        build_proxy=os.getenv("BUILD_PROXY") or None,
        build_proxy_container=os.getenv("BUILD_PROXY_CONTAINER") or None,
        runner_image=os.getenv("RUNNER_IMAGE") or None,
        web_runner_image=os.getenv("WEB_RUNNER_IMAGE") or None,
        node_image=os.getenv("NODE_IMAGE", "node:22-slim"),
        npm_install_timeout_s=_float("NPM_INSTALL_TIMEOUT_S", 420.0),
        web_timeout_s=_float("WEB_TIMEOUT_S", 300.0),
        hidden_test_timeout_s=_int("HIDDEN_TEST_TIMEOUT_S", 30),
        call_timeout_s=_float("CALL_TIMEOUT_S", 5.0),
        blackbox_suite_timeout_s=_float("BLACKBOX_SUITE_TIMEOUT_S", 300.0),
    )
