"""BUILD y servido de una entrega web (portado de v2 `backend/web/serve.py`).

- Estática (sin package.json): se sirve el workspace tal cual (solo lectura).
- Node (package.json + package-lock.json): se copia a un volumen y
  1. `npm ci` con red: en la VM, la red interna del build cuya única salida es el proxy con lista
     blanca (registry.npmjs.org). Los scripts de instalación SÍ corren (muchos paquetes los
     necesitan); el contenedor solo tiene el código del programador y sus dependencias, nunca
     tests ni secretos, y corre bajo gVisor como nobody.
  2. `npm run build` SIN red, si el proyecto define el script `build`;
  3. se sirve la primera carpeta con index.html entre dist/, build/, out/, public/ o la raíz.
- El servidor (http.server de Python, código nuestro) corre en una red interna, sin internet, y
  solo lo alcanza el contenedor de Playwright.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from verifier.config import get_settings
from verifier.sandbox.runner import (
    Mount,
    SandboxLimits,
    SandboxResult,
    SandboxUnavailable,
    Service,
    _docker,
    container_ip,
    ensure_image,
    run_in_sandbox,
    start_service,
)

SITE_MOUNT = "/site"
SITE_PORT = 8080
_NPM_ENV = {"npm_config_cache": "/tmp/.npm", "npm_config_update_notifier": "false", "npm_config_fund": "false",
            "npm_config_audit": "false"}
# Caché de npm compartida entre BUILDs (solo en `npm ci`). Es direccionada por contenido y npm
# verifica el `integrity` del lockfile al leerla: un BUILD no puede envenenar paquetes de otro.
NPM_CACHE_VOLUME = "cc-npm-cache"
NPM_CACHE_MOUNT = "/npm-cache"


def _runtime_args() -> list[str]:
    runtime = get_settings().sandbox_runtime
    return ["--runtime", runtime] if runtime else []


def _npm_cache_volume(image: str) -> str:
    if _docker(["volume", "inspect", NPM_CACHE_VOLUME]).returncode != 0:
        _docker(["volume", "create", NPM_CACHE_VOLUME])
        _docker(["run", "--rm", "--network", "none", "--user", "0", *_runtime_args(),
                 "--mount", f"type=volume,source={NPM_CACHE_VOLUME},target={NPM_CACHE_MOUNT}",
                 image, "chown", "65534:65534", NPM_CACHE_MOUNT], timeout_s=60)
    return NPM_CACHE_VOLUME


@dataclass
class SiteBuild:
    kind: str                       # static | npm
    site_mount: Mount
    subdir: str = "."
    install: SandboxResult | None = None
    build: SandboxResult | None = None
    volume: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def remove(self) -> None:
        if self.volume:
            _docker(["volume", "rm", "--force", self.volume])

    def summary(self) -> dict:
        def sb(r: SandboxResult | None) -> dict | None:
            if r is None:
                return None
            return {"exit_code": r.exit_code, "duration_s": r.duration_s, "timed_out": r.timed_out,
                    "stdout_tail": r.stdout[-800:], "stderr_tail": r.stderr[-800:]}
        return {"kind": self.kind, "subdir": self.subdir, "error": self.error,
                "install": sb(self.install), "build": sb(self.build)}


def static_site(directory: Path) -> SiteBuild:
    return SiteBuild("static", Mount(str(directory), SITE_MOUNT))


def _proxy_env() -> dict[str, str]:
    s = get_settings()
    proxy = s.build_proxy
    if s.build_proxy_container:
        proxy = f"http://{container_ip(s.build_proxy_container, s.build_network)}:3128"
    if not proxy:
        return {}
    return {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "npm_config_https_proxy": proxy, "npm_config_proxy": proxy}


def _limits(install: bool) -> SandboxLimits:
    s = get_settings()
    base = SandboxLimits.from_settings()
    return replace(base, timeout_s=s.npm_install_timeout_s if install else s.sandbox_timeout_s * 2,
                   memory=s.build_memory, pids=512, cpus=max(base.cpus, 2.0))


def prepare_site(workspace: Path) -> SiteBuild:
    if not (workspace / "package.json").exists():
        return static_site(workspace)

    s = get_settings()
    image = s.node_image
    ensure_image(image)
    volume = f"cc-web-{uuid.uuid4().hex[:12]}"
    if _docker(["volume", "create", volume]).returncode != 0:
        raise SandboxUnavailable("no se pudo crear el volumen del sitio")
    site = SiteBuild("npm", Mount(volume, SITE_MOUNT, kind="volume"), volume=volume)
    # Copia como root a un volumen propio (solo copia: no ejecuta nada de la entrega).
    copy = _docker([
        "run", "--rm", "--network", "none", "--user", "0", *_runtime_args(),
        "--mount", f"type=volume,source={volume},target=/workspace",
        "--mount", Mount(str(workspace), "/src").arg(),
        image, "sh", "-c", "cp -a /src/. /workspace/ && chown -R 65534:65534 /workspace",
    ], timeout_s=120)
    if copy.returncode != 0:
        site.error = f"no se pudo preparar el proyecto: {copy.stderr[-300:]}"
        return site

    rw = (Mount(volume, "/workspace", readonly=False, kind="volume"),)
    cache = _npm_cache_volume(image)
    site.install = run_in_sandbox(
        None, "cd /workspace && npm ci --no-audit --loglevel=error",
        None, network=s.build_network, limits=_limits(True), image=image, tmp_size="512m",
        mounts=(*rw, Mount(cache, NPM_CACHE_MOUNT, readonly=False, kind="volume")),
        env={**_NPM_ENV, **_proxy_env(), "npm_config_cache": NPM_CACHE_MOUNT},
    )
    if site.install.exit_code != 0:
        site.error = ("npm ci superó el tiempo máximo" if site.install.timed_out
                      else "npm ci falló (¿lockfile desactualizado o paquete inexistente?)")
        return site

    with_tmp = dict(image=image, mounts=rw, env=_NPM_ENV, tmp_size="512m")
    try:
        scripts = json.loads((workspace / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
    except (ValueError, UnicodeDecodeError, AttributeError):
        scripts = {}
    if isinstance(scripts, dict) and "build" in scripts:
        site.build = run_in_sandbox(None, "cd /workspace && npm run build", None,
                                    network=False, limits=_limits(False), **with_tmp)
        if site.build.exit_code != 0 or site.build.timed_out:
            site.error = "npm run build falló (corre sin red)"
            return site

    found = run_in_sandbox(
        None,
        'cd /workspace && for d in dist build out public .; do [ -f "$d/index.html" ] && echo "$d" && exit 0; done; exit 1',
        None, network=False, limits=_limits(False), **with_tmp,
    )
    if found.exit_code != 0:
        site.error = "el build no produjo index.html (dist/, build/, out/, public/ o la raíz)"
        return site
    site.subdir = found.stdout.strip().splitlines()[0]
    return site


def serve_site(site: SiteBuild, network: str) -> tuple[Service, str]:
    """Levanta el servidor estático (código nuestro) y devuelve (servicio, URL base por IP)."""
    s = get_settings()
    limits = replace(SandboxLimits.from_settings(), timeout_s=s.web_timeout_s + 120)
    service = start_service(
        None,
        ["python", "-I", "-m", "http.server", str(SITE_PORT), "--bind", "0.0.0.0",
         "--directory", f"{SITE_MOUNT}/{site.subdir}"],
        image=s.sandbox_image, limits=limits, network=network, alias="web", mounts=(site.site_mount,),
    )
    try:
        ip = container_ip(service.name, network)
    except SandboxUnavailable:
        service.remove()
        raise
    return service, f"http://{ip}:{SITE_PORT}"
