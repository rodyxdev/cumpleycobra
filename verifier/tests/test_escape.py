"""Prueba de escape (evidencia del SOW, plan de mejora fase 3).

Una entrega maliciosa intenta, desde el contenedor de la entrega:
- leer los metadatos de la nube (169.254.169.254) y salir a internet (IP y DNS);
- alcanzar la API en el host (host.docker.internal y la puerta de enlace de la red);
- escribir en el workspace, en la raíz del contenedor y fuera de /tmp;
- leer la suite oculta, el canal confiable o variables con secretos;
- agotar procesos (bomba de fork) y memoria.

Todo debe fallar, y cada intento queda registrado en el reporte del test. En la VM se repite con
`SANDBOX_RUNTIME=runsc` (gVisor): `python -m pytest verifier/tests/test_escape.py -q -rA`.
"""

import json

import pytest

from verifier.blackbox import run_blackbox
from verifier.verification.suite_files import write_suite_dir

from .helpers import requires_docker, script_spec, write_files

MALICIOSA = r'''
import json, os, socket, subprocess

def _conecta(host, port):
    try:
        socket.create_connection((host, port), timeout=2).close()
        return "CONECTÓ"
    except OSError as exc:
        return f"bloqueado ({type(exc).__name__})"

def _escribe(path):
    try:
        with open(path, "w") as fh:
            fh.write("x")
        return "ESCRIBIÓ"
    except OSError as exc:
        return f"bloqueado ({type(exc).__name__})"

def _existe(path):
    return "VISIBLE" if os.path.exists(path) else "no existe"

def intentar():
    r = {}
    r["metadatos_gce"] = _conecta("169.254.169.254", 80)
    r["internet_ip"] = _conecta("1.1.1.1", 443)
    try:
        socket.getaddrinfo("pypi.org", 443)
        r["dns_externo"] = "RESOLVIÓ"
    except OSError as exc:
        r["dns_externo"] = f"bloqueado ({type(exc).__name__})"
    r["api_host_docker"] = _conecta("host.docker.internal", 8000)
    r["puerta_de_enlace"] = _conecta("172.17.0.1", 8000)
    r["escribir_workspace"] = _escribe("/workspace/pwned.txt")
    r["escribir_raiz"] = _escribe("/etc/pwned")
    r["escribir_usr"] = _escribe("/usr/local/lib/pwned.py")
    r["suite_oculta"] = _existe("/hidden")
    r["canal_confiable"] = _existe("/cc/cc_channel.py")
    r["salida_junit"] = _existe("/out/junit.xml")
    # GPG_KEY viene de la imagen oficial de Python: es la huella pública de quien firma las versiones.
    r["secretos_en_entorno"] = sorted(k for k in os.environ if k != "GPG_KEY" and any(
        s in k for s in ("SECRET", "TOKEN", "KEY", "PASSWORD", "GOOGLE", "DATABASE", "ARBITER")))
    r["usuario"] = os.getuid()
    try:
        procs = []
        for _ in range(400):
            procs.append(subprocess.Popen(["sleep", "5"]))
        r["bomba_de_procesos"] = f"CREÓ {len(procs)}"
    except OSError as exc:
        r["bomba_de_procesos"] = f"bloqueado tras {len(procs)} ({type(exc).__name__})"
    finally:
        for p in procs:
            p.kill()
    return json.dumps(r, ensure_ascii=False)

def memoria():
    bloques = []
    while True:
        bloques.append(bytearray(64 * 1024 * 1024))
'''

TESTS = '''
import json
import pytest
from cc_channel import remote, SubmissionCrashed, SubmissionTimeout

intentar = remote("maliciosa", "intentar")
memoria = remote("maliciosa", "memoria")

def test_reporte():
    # Falla a propósito: así el reporte viaja en el mensaje del JUnit hasta el host.
    pytest.fail("REPORTE " + intentar())

def test_memoria():
    with pytest.raises((SubmissionCrashed, SubmissionTimeout)):
        memoria()
'''


@requires_docker
def test_la_entrega_no_escapa_del_contenedor(tmp_path, monkeypatch):
    monkeypatch.setenv("CALL_TIMEOUT_S", "20")
    ws = write_files(tmp_path / "ws", {"maliciosa.py": MALICIOSA})
    suite = tmp_path / "suite"
    write_suite_dir(suite, {"test_c1.py": TESTS})
    run = run_blackbox(ws, suite, script_spec("maliciosa", ["intentar", "memoria"]))
    outcomes = {o.name: o for o in run.outcomes}
    assert outcomes["test_memoria"].outcome == "passed", outcomes["test_memoria"].message
    message = outcomes["test_reporte"].message
    assert "REPORTE " in message, message
    # El atributo `message` del JUnit llega recortado; el texto completo viene después.
    candidates = [line.split("REPORTE ", 1)[1] for line in message.splitlines() if "REPORTE " in line]
    report = next(json.loads(c) for c in reversed(candidates) if c.rstrip().endswith("}"))
    print("\nPrueba de escape:\n" + json.dumps(report, ensure_ascii=False, indent=1))
    for key in ("metadatos_gce", "internet_ip", "api_host_docker", "puerta_de_enlace",
                "escribir_workspace", "escribir_raiz", "escribir_usr", "dns_externo"):
        assert report[key].startswith("bloqueado"), (key, report[key])
    for key in ("suite_oculta", "canal_confiable", "salida_junit"):
        assert report[key] == "no existe", (key, report[key])
    assert report["secretos_en_entorno"] == []
    assert report["usuario"] == 65534
    assert report["bomba_de_procesos"].startswith("bloqueado"), report["bomba_de_procesos"]
    assert not (ws / "pwned.txt").exists()
