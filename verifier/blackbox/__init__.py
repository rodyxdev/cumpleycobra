"""Verificación caja negra: la entrega y los tests corren en contenedores separados.

- SUT (no confiable): monta la entrega (solo lectura) y `/cc` con el relay/adaptador o el
  servidor ASGI. No ve los tests, ni el contrato, ni las salidas esperadas.
- Lado confiable: corre pytest con la suite oculta y `cc_channel`; NO monta la entrega.
  El JUnit lo escribe solo este contenedor y lo extrae el host.
- Ambos comparten una red Docker `--internal` (sin salida a internet); el SUT es `sut:8000`.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from verifier.config import get_settings
from verifier.contract import ExecutionSpec
from verifier.sandbox import Mount, SandboxLimits, SandboxResult, SandboxUnavailable, ensure_runner_image, run_in_sandbox
from verifier.sandbox.runner import InternalNetwork, _docker, container_ip, start_service
from verifier.verification.junit import TestOutcome, parse_junit

RUNTIME = Path(__file__).parent / "runtime"
SUT_FILES = ("cc_codec.py", "adapter.py", "relay.py", "serve_asgi.py")
TRUSTED_FILES = ("cc_codec.py", "cc_channel.py")
SUT_API_DIR = Path(__file__).parent / "sut_api_image"
HIDDEN_MOUNT = "/hidden"


@dataclass
class BlackboxRun:
    sandbox: SandboxResult          # contenedor confiable (pytest)
    outcomes: list[TestOutcome]
    report_found: bool
    sut_logs: str                   # stdout/stderr del SUT (texto NO confiable)
    sut_state: dict


def _copy_runtime(dest: Path, names: tuple[str, ...]) -> Path:
    dest.mkdir(parents=True)
    for name in names:
        shutil.copy2(RUNTIME / name, dest / name)
    return dest


def sut_api_image() -> str:
    import hashlib

    digest = hashlib.sha256((SUT_API_DIR / "Dockerfile").read_bytes()).hexdigest()[:12]
    tag = f"cumpleycobra-sut-api:{digest}"
    if _docker(["image", "inspect", tag]).returncode != 0:
        built = _docker(["build", "--tag", tag, str(SUT_API_DIR)], timeout_s=900)
        if built.returncode != 0:
            raise SandboxUnavailable(f"no se pudo construir {tag}: {built.stderr.strip()[-500:]}")
    return tag


def pytest_command(timeout_per_test: int) -> str:
    return (
        f"cd /tmp && python -I -m pytest {HIDDEN_MOUNT} -c {HIDDEN_MOUNT}/pytest.ini "
        f"--rootdir={HIDDEN_MOUNT} -p no:cacheprovider -q -rN --timeout={timeout_per_test} "
        "--continue-on-collection-errors --junitxml=/out/junit.xml"
    )


def run_blackbox(workspace: Path, suite_dir: Path, spec: ExecutionSpec, *, deps_mount: Mount | None = None) -> BlackboxRun:
    s = get_settings()
    limits = SandboxLimits.from_settings()
    runner = ensure_runner_image()
    if spec.profile == "api":
        app = next(sym for sym in spec.interface.symbols if sym.kind == "asgi_app")
        image = sut_api_image()
        entrypoint = ["python", "-I", "/cc/serve_asgi.py", f"{app.module}:{app.name}"]
        env = {}
    else:
        image = s.sandbox_image
        entrypoint = ["python", "-I", "/cc/relay.py"]
        symbols = ",".join(f"{sym.module}:{sym.name}" for sym in spec.interface.symbols)
        env = {"CC_SYMBOLS": symbols, "CC_CALL_TIMEOUT": str(s.call_timeout_s)}

    with tempfile.TemporaryDirectory(prefix="cc-bb-") as tmp:
        tmp = Path(tmp)
        sut_rt = _copy_runtime(tmp / "sut", SUT_FILES)
        trusted_rt = _copy_runtime(tmp / "trusted", TRUSTED_FILES)
        network = InternalNetwork()
        sut = None
        try:
            mounts = [Mount(str(sut_rt), "/cc")] + ([deps_mount] if deps_mount else [])
            sut = start_service(workspace, entrypoint, image=image, limits=limits, network=network.name,
                                alias="sut", mounts=tuple(mounts), env=env)
            out = tmp / "out"
            trusted_limits = SandboxLimits(limits.cpus, limits.memory, limits.pids, s.blackbox_suite_timeout_s,
                                           limits.output_limit, limits.out_tmpfs_bytes)
            result = run_in_sandbox(
                None, pytest_command(s.hidden_test_timeout_s), out,
                image=runner, limits=trusted_limits, network=network.name,
                mounts=(Mount(str(suite_dir), HIDDEN_MOUNT), Mount(str(trusted_rt), "/cc")),
                # Por IP y no por el alias `sut`: bajo gVisor el DNS interno de Docker no resuelve.
                env={"CC_SUT_URL": f"http://{container_ip(sut.name, network.name)}:8000",
                     "CC_CALL_TIMEOUT": str(s.call_timeout_s)},
            )
            report = out / "junit.xml"
            outcomes = parse_junit(report.read_bytes()) if report.exists() else []
            return BlackboxRun(result, outcomes, report.exists(), sut.logs(), sut.state())
        finally:
            if sut is not None:
                sut.remove()
            network.remove()
