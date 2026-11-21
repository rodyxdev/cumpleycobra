"""El paso BUILD por la red interna y el proxy con lista blanca, igual que en la VM (fase 3).

Levanta la misma topología que `verifier/deploy/startup.sh`: una red `--internal` para el build y el
proxy squid conectado a ella y a una red de salida. Comprueba que pip instala desde PyPI por el
proxy, que el contenedor del build no tiene salida directa y que el proxy rechaza otros dominios.
"""

import subprocess
import uuid
from pathlib import Path

import pytest

from verifier.sandbox import DepsVolume, build_dependencies, run_in_sandbox, SandboxLimits

from .helpers import requires_docker

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def docker(*args, check=True, timeout=600):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout,
                          encoding="utf-8", errors="replace")


@pytest.fixture
def build_network(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    internal, egress, proxy = f"cc-build-{suffix}", f"cc-salida-{suffix}", f"cc-proxy-{suffix}"
    docker("build", "-q", "-t", "cyc-proxy:test", str(DEPLOY / "proxy"))
    docker("network", "create", "--internal", internal)
    docker("network", "create", egress)
    try:
        docker("run", "-d", "--name", proxy, "--read-only", "--tmpfs", "/var/spool/squid", "--tmpfs", "/var/log/squid",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--network", egress, "cyc-proxy:test")
        docker("network", "connect", "--alias", "proxy", internal, proxy)
        monkeypatch.setenv("BUILD_NETWORK", internal)
        monkeypatch.setenv("BUILD_PROXY", "http://proxy:3128")
        yield internal
    finally:
        docker("rm", "-f", proxy, check=False)
        docker("network", "rm", internal, check=False)
        docker("network", "rm", egress, check=False)


@requires_docker
@pytest.mark.network
def test_pip_instala_por_el_proxy_y_nada_mas_sale(build_network, tmp_path):
    image = "python:3.12-slim"
    volume = DepsVolume(image)
    try:
        build = build_dependencies(["six==1.17.0"], volume, image)
        assert build.exit_code == 0, build.stderr[-1500:]
        assert build.network == build_network
    finally:
        volume.remove()

    ws = tmp_path / "ws"
    ws.mkdir()
    probe = (
        "python - <<'EOF'\n"
        "import socket, urllib.request, os\n"
        "def directo():\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 443), timeout=3); return 'CONECTÓ'\n"
        "    except OSError: return 'bloqueado'\n"
        "def por_proxy(url):\n"
        "    h = urllib.request.ProxyHandler({'https': 'http://proxy:3128'})\n"
        "    try:\n"
        "        urllib.request.build_opener(h).open(url, timeout=10); return 'PERMITIDO'\n"
        "    except Exception as exc: return 'rechazado'\n"
        "print('directo', directo())\n"
        "print('pypi', por_proxy('https://pypi.org/simple/six/'))\n"
        "print('github', por_proxy('https://github.com/'))\n"
        "print('metadatos', por_proxy('http://169.254.169.254/computeMetadata/v1/'))\n"
        "EOF"
    )
    limits = SandboxLimits(cpus=0.5, memory="256m", pids=64, timeout_s=60, output_limit=4096)
    result = run_in_sandbox(ws, probe, None, image=image, limits=limits, network=build_network)
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines())
    assert lines == {"directo": "bloqueado", "pypi": "PERMITIDO", "github": "rechazado", "metadatos": "rechazado"}, result.stdout + result.stderr
