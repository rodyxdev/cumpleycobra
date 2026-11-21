"""Paso BUILD (con red): instala las dependencias declaradas en un volumen de Docker.

El paso TEST monta luego ese volumen en `/deps` de solo lectura y corre sin red.

Mitigaciones de pip:
- `--only-binary=:all:`: solo wheels. Un sdist ejecutaría `setup.py`/el backend de build,
  es decir, código arbitrario del paquete *durante la instalación*. Con wheels no se ejecuta nada al instalar.
- `--target /deps` + `sys.path.append` desde nuestro conftest: `/deps` no es un directorio
  "site", así que los `.pth` que traiga un wheel no se procesan al arrancar Python.
- La lista de requisitos no es el archivo del freelancer: la arma el backend con
  nombres validados contra `allowed_dependencies` (sin URLs, `-e`, `--index-url`, rutas).
- Red: `BUILD_NETWORK`. En la VM es una red interna de Docker sin ruta a internet, y la
  única salida es el proxy `BUILD_PROXY`, con lista blanca de PyPI (plan de mejora, fase 3).
Riesgo residual: el código de las dependencias sí se ejecuta en TEST (al importarse),
aunque sin red; y un paquete permitido puede estar comprometido (cadena de suministro).
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from verifier.config import get_settings
from verifier.sandbox.runner import (
    Mount,
    SandboxLimits,
    SandboxResult,
    SandboxUnavailable,
    _docker,
    container_ip,
    ensure_image,
    run_in_sandbox,
)

RUNNER_DIR = Path(__file__).parent / "runner_image"
DEPS_MOUNT = "/deps"


def runner_image_tag() -> str:
    """Etiqueta de la imagen de tests: derivada del Dockerfile para que cambie si cambia."""
    configured = get_settings().runner_image
    if configured:
        return configured
    digest = hashlib.sha256((RUNNER_DIR / "Dockerfile").read_bytes()).hexdigest()[:12]
    return f"cumpleycobra-runner:{digest}"


def ensure_runner_image() -> str:
    tag = runner_image_tag()
    if _docker(["image", "inspect", tag]).returncode == 0:
        return tag
    if get_settings().runner_image:
        ensure_image(tag)
        return tag
    built = _docker(["build", "--tag", tag, str(RUNNER_DIR)], timeout_s=900)
    if built.returncode != 0:
        raise SandboxUnavailable(f"no se pudo construir {tag}: {built.stderr.strip()[-500:]}")
    return tag


class DepsVolume:
    """Volumen de Docker con las dependencias instaladas de una entrega."""

    def __init__(self, image: str):
        self.name = f"cc-deps-{uuid.uuid4().hex[:12]}"
        created = _docker(["volume", "create", self.name])
        if created.returncode != 0:
            raise SandboxUnavailable(f"no se pudo crear el volumen: {created.stderr.strip()[-300:]}")
        # El volumen nace de root; se cede a nobody con un contenedor sin red que solo hace chown.
        chown = _docker([
            "run", "--rm", "--network", "none", "--user", "0",
            "--mount", f"type=volume,source={self.name},target={DEPS_MOUNT}",
            image, "chown", "65534:65534", DEPS_MOUNT,
        ], timeout_s=60)
        if chown.returncode != 0:
            self.remove()
            raise SandboxUnavailable(f"no se pudo preparar el volumen: {chown.stderr.strip()[-300:]}")

    def mount(self) -> Mount:
        return Mount(self.name, DEPS_MOUNT, readonly=True, kind="volume")

    def remove(self) -> None:
        _docker(["volume", "rm", "--force", self.name])


def build_dependencies(requirements: list[str], volume: DepsVolume, image: str) -> SandboxResult:
    """Instala `requirements` (ya validados) en `volume`, con red y su propio timeout."""
    s = get_settings()
    limits = replace(SandboxLimits.from_settings(), timeout_s=s.build_timeout_s, memory=s.build_memory)
    with tempfile.TemporaryDirectory(prefix="cc-req-") as tmp:
        req_dir = Path(tmp)
        # mkdtemp crea 0700; el contenedor corre como nobody y necesita leer requirements.txt.
        req_dir.chmod(0o755)
        (req_dir / "requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")
        env = {}
        proxy = s.build_proxy
        if s.build_proxy_container:
            proxy = f"http://{container_ip(s.build_proxy_container, s.build_network)}:3128"
        if proxy:
            env = {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "PIP_PROXY": proxy}
        command = (
            "pip install --no-input --disable-pip-version-check --no-cache-dir --progress-bar off "
            f"--only-binary=:all: --target {DEPS_MOUNT} -r /workspace/requirements.txt"
        )
        return run_in_sandbox(
            req_dir, command, req_dir / "out",
            image=image, limits=limits, network=s.build_network, env=env,
            mounts=(Mount(volume.name, DEPS_MOUNT, readonly=False, kind="volume"),),
        )
