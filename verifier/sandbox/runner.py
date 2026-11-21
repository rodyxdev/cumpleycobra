"""Ejecución aislada de comandos en un contenedor Docker.

Aislamiento aplicado a cada ejecución:
- `--network none` por defecto (el paso BUILD es el único que pide red).
- `--cpus`, `--memory` (= `--memory-swap`, sin swap) y `--pids-limit`.
- `--user 65534:65534` (nobody), `--cap-drop ALL`, `--security-opt no-new-privileges`.
- raíz del contenedor de solo lectura (`--read-only`) con un `/tmp` tmpfs pequeño.
- workspace montado en `/workspace` de solo lectura; `/out` es un tmpfs con tamaño máximo.
- límite de tiempo de pared: al vencer se mata el contenedor por nombre.
- runtime `SANDBOX_RUNTIME` (gVisor, `runsc`, en la VM): un kernel en espacio de usuario
  entre el código ajeno y el del host. Se aplica a todos los contenedores.

Modelo de ejecución: el contenedor arranca en espera (`sleep`), el comando corre con
`docker exec` y, al terminar, el contenido de `/out` se extrae con `tar` por stdout
(un tmpfs desaparece al parar el contenedor, así que hay que leerlo mientras vive).

stdout/stderr se leen en streaming y se conservan solo los primeros N bytes, para
que una salida infinita no agote la memoria del verifier.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from verifier.config import get_settings

SANDBOX_UID = "65534:65534"
WORKSPACE_MOUNT = "/workspace"
OUTPUT_MOUNT = "/out"
_CHUNK = 64 * 1024
# El contenedor se autodestruye aunque el backend muera a mitad de ejecución.
_IDLE_GRACE_S = 120


class SandboxUnavailable(RuntimeError):
    """Docker no está disponible o la imagen no se pudo preparar."""


@dataclass(frozen=True)
class SandboxLimits:
    cpus: float
    memory: str
    pids: int
    timeout_s: float
    output_limit: int
    out_tmpfs_bytes: int = 16 * 1024 * 1024

    @classmethod
    def from_settings(cls) -> "SandboxLimits":
        s = get_settings()
        return cls(
            s.sandbox_cpus, s.sandbox_memory, s.sandbox_pids, s.sandbox_timeout_s,
            s.sandbox_output_limit, s.sandbox_out_bytes,
        )


@dataclass(frozen=True)
class Mount:
    """Montaje adicional. `kind` es `bind` (ruta del host) o `volume` (volumen de Docker)."""

    source: str
    target: str
    readonly: bool = True
    kind: str = "bind"

    def arg(self) -> str:
        source = str(Path(self.source).resolve()) if self.kind == "bind" else self.source
        if "," in source or "," in self.target:
            raise ValueError(f"ruta no montable (contiene ','): {source}")
        spec = f"type={self.kind},source={source},target={self.target}"
        return spec + (",readonly" if self.readonly else "")


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None  # None si se mató por timeout
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_s: float
    timed_out: bool
    oom_killed: bool
    image: str
    command: str
    network: bool | str = False
    output_files: list[str] = field(default_factory=list)


class _CappedReader(threading.Thread):
    """Drena un pipe completo guardando solo los primeros `limit` bytes."""

    def __init__(self, stream, limit: int):
        super().__init__(daemon=True)
        self.stream, self.limit = stream, limit
        self.buf = bytearray()
        self.total = 0

    def run(self) -> None:
        while chunk := self.stream.read(_CHUNK):
            self.total += len(chunk)
            room = self.limit - len(self.buf)
            if room > 0:
                self.buf += chunk[:room]

    @property
    def truncated(self) -> bool:
        return self.total > self.limit

    def text(self) -> str:
        return self.buf.decode("utf-8", errors="replace")


def _docker(args: list[str], timeout_s: float = 30, text: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=text, timeout=timeout_s,
                              encoding="utf-8" if text else None, errors="replace" if text else None)
    except FileNotFoundError as exc:
        raise SandboxUnavailable("no se encontró el binario 'docker'") from exc
    except subprocess.TimeoutExpired as exc:
        raise SandboxUnavailable(f"'docker {args[0]}' no respondió en {timeout_s}s") from exc


def docker_available() -> bool:
    try:
        return _docker(["version", "--format", "{{.Server.Version}}"], timeout_s=15).returncode == 0
    except SandboxUnavailable:
        return False


def ensure_image(image: str, pull_timeout_s: float = 600) -> None:
    """Descarga la imagen si falta (fuera del tiempo medido de la ejecución)."""
    if _docker(["image", "inspect", image]).returncode == 0:
        return
    pulled = _docker(["pull", image], timeout_s=pull_timeout_s)
    if pulled.returncode != 0:
        raise SandboxUnavailable(f"no se pudo descargar {image}: {pulled.stderr.strip()[-300:]}")


def _network_arg(network: bool | str) -> str:
    if isinstance(network, str):
        return network  # red con nombre (p. ej. una red interna de Docker)
    return "bridge" if network else "none"


def build_docker_args(
    name: str,
    image: str,
    workspace: Path | None,
    limits: SandboxLimits,
    *,
    network: bool | str = False,
    mounts: tuple[Mount, ...] = (),
    env: dict[str, str] | None = None,
    entrypoint: list[str] | None = None,
    extra: list[str] | None = None,
    tmp_size: str = "64m",
    runtime: str | None = None,
) -> list[str]:
    """Argumentos de `docker run --detach`.

    Sin `entrypoint`, el contenedor queda en espera (`sleep`) para usarlo con `docker exec`.
    Sin `workspace`, la entrega no se monta (contenedores del lado confiable).
    """
    args = [
        "docker", "run", "--detach",
        "--name", name,
        "--pull", "never",
        "--network", _network_arg(network),
    ]
    runtime = runtime if runtime is not None else get_settings().sandbox_runtime
    if runtime:
        args += ["--runtime", runtime]
    args += [
        "--cpus", str(limits.cpus),
        "--memory", limits.memory,
        "--memory-swap", limits.memory,
        "--pids-limit", str(limits.pids),
        "--user", SANDBOX_UID,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", f"/tmp:rw,nosuid,nodev,size={tmp_size}",
        "--mount", f"type=tmpfs,target={OUTPUT_MOUNT},tmpfs-size={limits.out_tmpfs_bytes},tmpfs-mode=1777",
    ]
    if workspace is not None:
        args += ["--mount", Mount(str(workspace), WORKSPACE_MOUNT).arg()]
    for m in mounts:
        args += ["--mount", m.arg()]
    args += ["--workdir", WORKSPACE_MOUNT if workspace is not None else "/tmp"]
    merged_env = {"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "OUTPUT_DIR": OUTPUT_MOUNT, **(env or {})}
    for key, value in merged_env.items():
        args += ["--env", f"{key}={value}"]
    args += extra or []
    args += [image, *(entrypoint or ["sleep", str(int(limits.timeout_s) + _IDLE_GRACE_S)])]
    return args


def _extract_out(name: str, output_dir: Path) -> list[str]:
    """Copia `/out` del contenedor al host. Tamaño acotado por el tmpfs."""
    proc = _docker(["exec", name, "tar", "-C", OUTPUT_MOUNT, "-cf", "-", "."], timeout_s=60, text=False)
    if proc.returncode != 0 or not proc.stdout:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        members = [m for m in tar.getmembers() if m.isfile() or m.isdir()]
        if hasattr(tarfile, "data_filter"):
            # filtro "data": rechaza rutas absolutas, `..`, enlaces fuera del destino y dispositivos.
            tar.extractall(output_dir, members=members, filter="data")
        else:
            # Python sin filtros de tarfile (Debian 12 trae 3.11.2): la misma defensa a mano.
            root = output_dir.resolve()
            for m in members:
                target = (root / m.name).resolve()
                if m.name.startswith("/") or not target.is_relative_to(root):
                    raise SandboxUnavailable(f"ruta no permitida en /out: {m.name!r}")
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, target.open("wb") as dst:
                    dst.write(src.read())
        return sorted(m.name.removeprefix("./") for m in members if m.isfile())


def run_in_sandbox(
    workspace: Path | None,
    command: str,
    output_dir: Path | None,
    *,
    image: str | None = None,
    limits: SandboxLimits | None = None,
    network: bool | str = False,
    mounts: tuple[Mount, ...] = (),
    env: dict[str, str] | None = None,
    extra: list[str] | None = None,
    tmp_size: str = "64m",
) -> SandboxResult:
    """Ejecuta `command` (vía `sh -c`) dentro de un contenedor aislado."""
    image = image or get_settings().sandbox_image
    limits = limits or SandboxLimits.from_settings()
    ensure_image(image)

    name = f"cc-sbx-{uuid.uuid4().hex[:12]}"
    args = build_docker_args(name, image, workspace, limits, network=network, mounts=mounts, env=env,
                             extra=extra, tmp_size=tmp_size)
    try:
        created = _docker(args[1:], timeout_s=60)
        if created.returncode != 0:
            raise SandboxUnavailable(f"no se pudo crear el contenedor: {created.stderr.strip()[-300:]}")

        started = time.monotonic()
        proc = subprocess.Popen(
            ["docker", "exec", name, "sh", "-c", command],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        )
        out = _CappedReader(proc.stdout, limits.output_limit)
        err = _CappedReader(proc.stderr, limits.output_limit)
        out.start()
        err.start()

        timed_out = False
        try:
            proc.wait(timeout=limits.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _docker(["kill", name])
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        duration = time.monotonic() - started
        out.join(timeout=5)
        err.join(timeout=5)

        output_files = [] if timed_out or output_dir is None else _extract_out(name, output_dir)
        oom = _docker(["inspect", "--format", "{{.State.OOMKilled}}", name]).stdout.strip() == "true"
        exit_code = None if timed_out else proc.returncode
        return SandboxResult(
            exit_code=exit_code,
            stdout=out.text(),
            stderr=err.text(),
            stdout_truncated=out.truncated,
            stderr_truncated=err.truncated,
            duration_s=round(duration, 3),
            timed_out=timed_out,
            # Con `docker exec`, un OOM mata al proceso (137) sin marcar siempre el contenedor.
            oom_killed=oom or exit_code == 137,
            image=image,
            command=command,
            network=network,
            output_files=output_files,
        )
    finally:
        _docker(["rm", "--force", name])


@dataclass
class Service:
    """Contenedor de larga vida (p. ej. la entrega levantada como servidor)."""

    name: str
    image: str

    def logs(self, limit: int = 16 * 1024) -> str:
        proc = _docker(["logs", "--tail", "400", self.name], timeout_s=30)
        return (proc.stdout + proc.stderr)[-limit:]

    def state(self) -> dict:
        fmt = "{{.State.Running}}|{{.State.ExitCode}}|{{.State.OOMKilled}}"
        raw = _docker(["inspect", "--format", fmt, self.name]).stdout.strip().split("|")
        if len(raw) != 3:
            return {"running": False, "exit_code": None, "oom_killed": False}
        return {"running": raw[0] == "true", "exit_code": int(raw[1]), "oom_killed": raw[2] == "true"}

    def remove(self) -> None:
        _docker(["rm", "--force", self.name])


def start_service(
    workspace: Path | None,
    entrypoint: list[str],
    *,
    image: str,
    limits: SandboxLimits,
    network: str,
    alias: str,
    mounts: tuple[Mount, ...] = (),
    env: dict[str, str] | None = None,
) -> Service:
    ensure_image(image)
    name = f"cc-svc-{uuid.uuid4().hex[:12]}"
    args = build_docker_args(name, image, workspace, limits, network=network, mounts=mounts, env=env,
                             entrypoint=entrypoint, extra=["--network-alias", alias])
    created = _docker(args[1:], timeout_s=60)
    if created.returncode != 0:
        _docker(["rm", "--force", name])
        raise SandboxUnavailable(f"no se pudo crear el servicio: {created.stderr.strip()[-300:]}")
    return Service(name, image)


def container_ip(name: str, network: str) -> str:
    """IP de un contenedor en una red. Bajo gVisor el DNS interno de Docker (alias de red) no
    funciona: el stack de red de runsc no usa las reglas iptables del contenedor. Por IP sí conecta."""
    fmt = '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % network
    ip = _docker(["inspect", "--format", fmt, name]).stdout.strip()
    if not ip or ip == "<no value>":
        raise SandboxUnavailable(f"el contenedor {name} no tiene IP en la red {network}")
    return ip


class InternalNetwork:
    """Red Docker `--internal`: los contenedores se ven entre sí pero no salen a internet."""

    def __init__(self):
        self.name = f"cc-net-{uuid.uuid4().hex[:12]}"
        created = _docker(["network", "create", "--internal", self.name])
        if created.returncode != 0:
            raise SandboxUnavailable(f"no se pudo crear la red interna: {created.stderr.strip()[-300:]}")

    def remove(self) -> None:
        _docker(["network", "rm", self.name])
