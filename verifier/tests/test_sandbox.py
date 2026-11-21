import time
from pathlib import Path

import pytest

from verifier.sandbox import (
    DepsVolume,
    SandboxLimits,
    build_dependencies,
    build_docker_args,
    docker_available,
    run_in_sandbox,
)

LIMITS = SandboxLimits(cpus=0.5, memory="256m", pids=64, timeout_s=5, output_limit=1024, out_tmpfs_bytes=1024 * 1024)

from .helpers import requires_docker


def test_docker_args_enforce_isolation(tmp_path):
    ws = tmp_path / "ws"
    args = build_docker_args("cc-sbx-test", "img:1", ws, LIMITS)
    joined = " ".join(args)
    assert ["--network", "none"] == args[args.index("--network"): args.index("--network") + 2]
    assert "--read-only" in args
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--user 65534:65534" in joined
    assert "--cpus 0.5" in joined
    assert "--memory 256m --memory-swap 256m" in joined
    assert "--pids-limit 64" in joined
    assert f"source={ws.resolve()},target=/workspace,readonly" in joined
    assert "type=tmpfs,target=/out,tmpfs-size=1048576" in joined
    assert args[-3:-1] == ["img:1", "sleep"]


def test_network_only_when_requested(tmp_path):
    args = build_docker_args("n", "img", tmp_path, LIMITS, network=True)
    assert args[args.index("--network") + 1] == "bridge"


@pytest.fixture
def workspace(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_bytes(b"hola desde el workspace\n")  # bytes: write_text pondría \r\n en Windows
    return ws


@requires_docker
def test_timeout_kills_container(workspace, tmp_path):
    started = time.monotonic()
    result = run_in_sandbox(workspace, "echo start; sleep 60; echo never", tmp_path / "out", limits=LIMITS)
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.exit_code is None
    assert "start" in result.stdout and "never" not in result.stdout
    assert elapsed < LIMITS.timeout_s + 15  # se mató, no esperó los 60 s
    assert 4.5 <= result.duration_s < LIMITS.timeout_s + 15


@requires_docker
def test_runs_command_and_captures_output(workspace, tmp_path):
    result = run_in_sandbox(workspace, "cat hello.txt; echo err >&2; exit 3", tmp_path / "out", limits=LIMITS)
    assert result.exit_code == 3
    assert result.stdout == "hola desde el workspace\n"
    assert result.stderr == "err\n"
    assert result.timed_out is False


@requires_docker
def test_isolation_inside_container(workspace, tmp_path):
    out = tmp_path / "out"
    cmd = (
        "id -u; "
        "touch /workspace/x 2>/dev/null && echo ws-writable || echo ws-readonly; "
        "touch /etc/x 2>/dev/null && echo root-writable || echo root-readonly; "
        "mkdir -p /out/sub && echo result > /out/sub/result.txt && echo out-writable; "
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\" "
        "2>/dev/null && echo net-on || echo net-off"
    )
    result = run_in_sandbox(workspace, cmd, out, limits=LIMITS)
    lines = result.stdout.split()
    assert lines == ["65534", "ws-readonly", "root-readonly", "out-writable", "net-off"]
    assert (out / "sub" / "result.txt").read_text().strip() == "result"
    assert result.output_files == ["sub/result.txt"]
    assert not (workspace / "x").exists()


@requires_docker
def test_out_tmpfs_has_size_limit(workspace, tmp_path):
    cmd = "dd if=/dev/zero of=/out/big bs=1024 count=4096 2>&1; echo rc=$?; du -k /out/big | cut -f1"
    result = run_in_sandbox(workspace, cmd, tmp_path / "out", limits=LIMITS)
    assert "No space left on device" in result.stdout
    written_kb = int(result.stdout.strip().split()[-1])
    assert written_kb <= 1024  # nunca más que el tmpfs de 1 MB


@requires_docker
def test_output_is_truncated(workspace, tmp_path):
    result = run_in_sandbox(workspace, "yes abcdefgh | head -c 100000", tmp_path / "out", limits=LIMITS)
    assert result.exit_code == 0
    assert len(result.stdout.encode()) == LIMITS.output_limit
    assert result.stdout_truncated is True
    assert result.stderr_truncated is False


@requires_docker
def test_oom_is_reported(workspace, tmp_path):
    result = run_in_sandbox(workspace, "python -c 'b = bytearray(1024**3)'", tmp_path / "out", limits=LIMITS)
    assert result.oom_killed is True
    assert result.exit_code == 137


@requires_docker
@pytest.mark.network
def test_build_with_network_then_test_without_network(workspace, tmp_path):
    image = "python:3.12-slim"
    volume = DepsVolume(image)
    try:
        build = build_dependencies(["six==1.17.0"], volume, image)
        assert build.exit_code == 0, build.stdout + build.stderr
        assert build.network == "bridge"
        cmd = (
            "python -c \"import sys; sys.path.append('/deps'); import six; print('six', six.__version__)\"; "
            "touch /deps/x 2>/dev/null && echo deps-writable || echo deps-readonly; "
            "python -c \"import socket; socket.create_connection(('pypi.org', 443), timeout=3)\" "
            "2>/dev/null && echo net-on || echo net-off"
        )
        test = run_in_sandbox(workspace, cmd, tmp_path / "out", image=image, limits=LIMITS, mounts=(volume.mount(),))
        assert test.stdout.split() == ["six", "1.17.0", "deps-readonly", "net-off"]
    finally:
        volume.remove()


@requires_docker
@pytest.mark.network
def test_build_refuses_sdist_only_packages(tmp_path):
    # --only-binary=:all: impide ejecutar setup.py de paquetes sin wheel.
    image = "python:3.12-slim"
    volume = DepsVolume(image)
    try:
        build = build_dependencies(["pyyaml==3.10"], volume, image)  # 3.10 solo existe como sdist
        assert build.exit_code != 0
        assert "No matching distribution" in build.stderr or "Could not find a version" in build.stderr
    finally:
        volume.remove()


def test_gvisor_runtime_from_settings(tmp_path, monkeypatch):
    assert "--runtime" not in build_docker_args("n", "img", tmp_path, LIMITS)
    monkeypatch.setenv("SANDBOX_RUNTIME", "runsc")
    args = build_docker_args("n", "img", tmp_path, LIMITS)
    assert args[args.index("--runtime") + 1] == "runsc"


def test_build_uses_configured_network_and_proxy(tmp_path, monkeypatch):
    import verifier.sandbox.build as build

    seen = {}

    def fake_run(workspace, command, output_dir, **kw):
        seen.update(kw, command=command)
        return None

    monkeypatch.setenv("BUILD_NETWORK", "cc-build")
    monkeypatch.setenv("BUILD_PROXY", "http://proxy:3128")
    monkeypatch.setattr(build, "run_in_sandbox", fake_run)
    build.build_dependencies(["six==1.17.0"], type("V", (), {"name": "vol"})(), "img")
    assert seen["network"] == "cc-build"
    assert seen["env"]["HTTPS_PROXY"] == "http://proxy:3128"
    assert "--only-binary=:all:" in seen["command"]
