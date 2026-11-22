"""Caja negra: codec, canal y aislamiento real entre la entrega y el lado confiable."""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from verifier.blackbox import RUNTIME, run_blackbox
from verifier.contract import ExecutionSpec, Interface, InterfaceSymbol
from verifier.sandbox import DepsVolume, build_dependencies, ensure_runner_image
from verifier.verification.suite_files import write_suite_dir

from .helpers import requires_docker, script_spec, write_files


def load_runtime(name):
    spec = importlib.util.spec_from_file_location(name, RUNTIME / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


codec = load_runtime("cc_codec")


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -5, 10**40, 1.5, "ñ", [], [1, [2]], (1, "a"), {"a": 1}, {1: "x", (1, 2): [3]},
     {"$tuple": 1}, {1, 2}, frozenset({"a"}), b"\x00\xff", {"k": (1, {2})}],
)
def test_codec_round_trip(value):
    import json

    assert codec.decode(json.loads(json.dumps(codec.encode(value)))) == value


def test_codec_preserves_types_json_would_lose():
    assert isinstance(codec.decode(codec.encode((1, 2))), tuple)
    assert codec.decode(codec.encode({1: "a"})) == {1: "a"}
    assert math.isnan(codec.decode(codec.encode(float("nan"))))


def test_codec_rejects_arbitrary_objects():
    with pytest.raises(TypeError):
        codec.encode(object())
    opaque = codec.decode({"$repr": "<x>", "$type": "Foo"})
    assert opaque != opaque and "no serializable" in repr(opaque)


def test_channel_maps_exceptions(monkeypatch):
    channel = load_runtime("cc_channel")
    responses = iter([
        {"status": "ok", "value": {"$tuple": [1, 2]}},
        {"status": "raised", "type": "ValueError", "module": "builtins", "message": "línea 3"},
        {"status": "raised", "type": "MiError", "module": "ventas", "message": "x"},
        {"status": "timeout", "message": "5s"},
        {"status": "crashed", "message": "exit 0"},
        {"status": "import_error", "message": "boom"},
        {"status": "raised", "type": "SystemExit", "module": "builtins", "message": "0"},
        {"status": "raised", "type": "StatisticsError", "module": "statistics", "message": "vacía",
         "builtin_base": "ValueError"},
    ])
    monkeypatch.setattr(channel, "_post", lambda path, payload: next(responses))
    f = channel.remote("ventas", "f")
    assert f() == (1, 2)
    with pytest.raises(ValueError, match="línea 3"):
        f()
    with pytest.raises(channel.RemoteException) as info:
        f()
    assert type(info.value).__name__ == "MiError"
    for expected in (channel.SubmissionTimeout, channel.SubmissionCrashed, channel.SubmissionImportError,
                     channel.SubmissionCrashed):
        with pytest.raises(expected):
            f()
    # Una excepción de biblioteca conserva su herencia builtin (StatisticsError es un ValueError).
    with pytest.raises(ValueError, match="vacía") as info:
        f()
    assert type(info.value).__name__ == "StatisticsError" and isinstance(info.value, channel.RemoteException)
    # Un fallo del canal no es una Exception: `pytest.raises(Exception)` no lo confunde con éxito.
    assert not issubclass(channel.ChannelError, Exception)



# --- Docker real ----------------------------------------------------------------------------

SUBMISSION = '''
import os, socket, sys

def doble(x):
    print("ruido en stdout que no debe romper el protocolo")
    return x * 2

def falla(n):
    raise ValueError(f"línea {n}: inválida")

def lento():
    import time
    time.sleep(30)

def espia():
    vistos = {}
    for ruta in ("/hidden", "/cc/cc_channel.py", "/out", "/tests"):
        vistos[ruta] = os.path.exists(ruta)
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=0.5)
        vistos["internet"] = True
    except OSError:
        vistos["internet"] = False
    try:
        socket.create_connection(("pypi.org", 443), timeout=0.5)
        vistos["dns_externo"] = True
    except OSError:
        vistos["dns_externo"] = False
    vistos["env"] = sorted(k for k in os.environ if "CC_" in k or "TEST" in k)
    return vistos

def salir():
    os._exit(0)
'''

TESTS = '''
import pytest
from cc_channel import remote, SubmissionTimeout, SubmissionCrashed

doble = remote("mod", "doble")
falla = remote("mod", "falla")
lento = remote("mod", "lento")
espia = remote("mod", "espia")
salir = remote("mod", "salir")

def test_valores_viajan():
    assert doble(21) == 42
    assert doble((1, 2)) == (1, 2, 1, 2)

def test_excepcion_builtin():
    with pytest.raises(ValueError, match="línea 7"):
        falla(7)

def test_timeout_por_llamada():
    with pytest.raises(SubmissionTimeout):
        lento()

def test_aislamiento_del_sut():
    vistos = espia()
    assert vistos["/hidden"] is False and vistos["/tests"] is False
    assert vistos["/cc/cc_channel.py"] is False
    assert vistos["internet"] is False and vistos["dns_externo"] is False
    assert vistos["env"] == ["CC_CALL_TIMEOUT", "CC_SYMBOLS"]

def test_os_exit_es_un_fallo():
    with pytest.raises(SubmissionCrashed, match="exit 0"):
        salir()

def test_lado_confiable_no_ve_la_entrega():
    import os
    assert not os.path.exists("/workspace")
'''


def script_draft(symbols):
    return script_spec("mod", symbols)


@requires_docker
def test_blackbox_script_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("CALL_TIMEOUT_S", "2")
    ws = write_files(tmp_path / "ws", {"mod.py": SUBMISSION})
    suite = tmp_path / "suite"
    write_suite_dir(suite, {"test_c1.py": TESTS})
    run = run_blackbox(ws, suite, script_draft(["doble", "falla", "lento", "espia", "salir"]))
    results = {o.name: (o.outcome, o.message[:300]) for o in run.outcomes}
    assert all(outcome == "passed" for outcome, _ in results.values()), results
    assert len(results) == 6
    assert "[entrega] ruido en stdout" in run.sut_logs


@requires_docker
def test_relay_only_serves_interface_symbols(tmp_path):
    ws = write_files(tmp_path / "ws", {"mod.py": SUBMISSION})
    suite = tmp_path / "suite"
    write_suite_dir(suite, {"test_c1.py": (
        "import pytest\nfrom cc_channel import remote, MissingSymbol\n"
        "def test_x():\n    with pytest.raises(MissingSymbol):\n        remote('os', 'system')('id')\n"
    )})
    run = run_blackbox(ws, suite, script_draft(["doble"]))
    assert [o.outcome for o in run.outcomes] == ["passed"]


API_APP = '''
from fastapi import FastAPI

app = FastAPI()
estado = {"arrancó": False}

@app.on_event("startup")
def inicio():
    estado["arrancó"] = True

@app.get("/saludo")
def saludo(nombre: str = "mundo"):
    return {"hola": nombre, "lifespan": estado["arrancó"]}

@app.post("/eco")
def eco(datos: dict):
    return datos
'''

API_TESTS = '''
from cc_channel import api

def test_get():
    r = api.get("/saludo", params={"nombre": "Ana"})
    assert r.status_code == 200
    assert r.json() == {"hola": "Ana", "lifespan": True}

def test_post():
    assert api.post("/eco", json={"a": [1, 2]}).json() == {"a": [1, 2]}

def test_404():
    assert api.get("/no-existe").status_code == 404
'''


@requires_docker
@pytest.mark.network
def test_blackbox_api_profile_end_to_end(tmp_path):
    ws = write_files(tmp_path / "ws", {"app.py": API_APP, "requirements.txt": "fastapi==0.162.0\n"})
    suite = tmp_path / "suite"
    write_suite_dir(suite, {"test_c1.py": API_TESTS})
    app = InterfaceSymbol(module="app", name="app", kind="asgi_app", signature="app")
    draft = ExecutionSpec(profile="api", interface=Interface(symbols=[app]), allowed_dependencies=["fastapi"])
    image = ensure_runner_image()
    volume = DepsVolume(image)
    try:
        build = build_dependencies(["fastapi==0.162.0"], volume, image)
        assert build.exit_code == 0, build.stderr[-2000:]
        run = run_blackbox(ws, suite, draft, deps_mount=volume.mount())
    finally:
        volume.remove()
    results = {o.name: (o.outcome, o.message[:300]) for o in run.outcomes}
    assert results and all(outcome == "passed" for outcome, _ in results.values()), (results, run.sut_logs[-2000:])


def test_runtime_files_are_split_by_side():
    from verifier.blackbox import SUT_FILES, TRUSTED_FILES

    assert "cc_channel.py" not in SUT_FILES
    assert not {"adapter.py", "relay.py"} & set(TRUSTED_FILES)
    assert all((RUNTIME / f).exists() for f in (*SUT_FILES, *TRUSTED_FILES))
    assert Path(RUNTIME).is_dir()
