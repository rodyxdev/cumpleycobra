"""Encendido de la VM del verificador (fase 3): la API la enciende cuando hay trabajo."""

import asyncio

import httpx
import pytest

from backend import main
from backend.ejecucion import arranque
from backend.tests.test_verificador import accepted_task, create_task, fake_llm, submit, world  # noqa: F401

URL = "https://compute.googleapis.com/compute/v1/projects/p/zones/z/instances/vm"


class Creds:
    valid, token = True, "t"


def starter(status, calls, clock=None, fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer t"
        if fail:
            return httpx.Response(403, json={"error": {"message": "sin permiso"}})
        if request.method == "GET":
            return httpx.Response(200, json={"status": status})
        return httpx.Response(200, json={"kind": "compute#operation"})

    kw = {"clock": clock} if clock else {}
    return arranque.VmStarter("p", "z", "vm", credentials=Creds(), transport=httpx.MockTransport(handler), **kw)


def test_enciende_la_vm_detenida():
    calls = []
    assert asyncio.run(starter("TERMINATED", calls).check_and_start()) == "STARTING"
    assert calls == [("GET", URL), ("POST", URL + "/start")]


def test_no_toca_una_vm_encendida():
    calls = []
    assert asyncio.run(starter("RUNNING", calls).check_and_start()) == "RUNNING"
    assert calls == [("GET", URL)]


def test_un_error_de_google_no_rompe_nada():
    calls = []
    assert asyncio.run(starter("TERMINATED", calls, fail=True).check_and_start()) is None
    assert calls == [("GET", URL)]


def test_revisa_como_mucho_una_vez_cada_30_s():
    calls, now = [], [1000.0]
    s = starter("RUNNING", calls, clock=lambda: now[0])

    async def go():
        s.poke()
        await s._task
        s.poke()               # dentro de los 30 s: no revisa
        now[0] += arranque.MIN_INTERVAL_SECS
        s.poke()
        await s._task

    asyncio.run(go())
    assert calls == [("GET", URL), ("GET", URL)]


def test_si_se_estaba_apagando_vuelve_a_revisar_pronto():
    calls, now = [], [1000.0]
    s = starter("STOPPING", calls, clock=lambda: now[0])

    async def go():
        s.poke()
        await s._task
        now[0] += arranque.STOPPING_RECHECK_SECS
        s.poke()
        await s._task

    asyncio.run(go())
    assert len(calls) == 2


def test_sin_variable_no_hay_encendido(monkeypatch):
    monkeypatch.delenv("VERIFIER_VM_NAME", raising=False)
    assert arranque.make_starter() is None
    monkeypatch.setenv("VERIFIER_VM_NAME", "cyc-verificador")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto")
    monkeypatch.delenv("VERIFIER_VM_ZONE", raising=False)
    s = arranque.make_starter()
    assert s.url.endswith("/projects/proyecto/zones/us-central1-a/instances/cyc-verificador")


class Spy:
    def __init__(self):
        self.pokes = 0

    def poke(self):
        self.pokes += 1


def test_la_api_enciende_al_encolar_y_al_consultar_en_cola(world, monkeypatch):  # noqa: F811
    spy = Spy()
    monkeypatch.setattr(main.app.state, "vm_starter", None, raising=False)
    created, ft = accepted_task(world)
    monkeypatch.setattr(main.app.state, "vm_starter", spy, raising=False)
    world.get(f"/tasks/{created['task_id']}")        # suite lista: no hace falta la VM
    assert spy.pokes == 0
    r = submit(world, created["task_id"], ft, {"kind": "code", "code": "x = 1"})
    assert r.status_code == 202 and spy.pokes == 1   # encolar la verificación
    world.get(f"/verificaciones/{r.json()['verification_id']}", headers={"X-Freelancer-Token": ft})
    assert spy.pokes == 2                            # sigue en cola

    other = create_task(world)                       # encola la suite de otra tarea
    assert spy.pokes == 3
    world.get(f"/tasks/{other['task_id']}")          # la suite espera: vuelve a revisar
    world.get(f"/tasks/{other['task_id']}/suite")
    assert spy.pokes == 5


@pytest.mark.parametrize("status", ["RUNNING", "TERMINATED"])
def test_poke_sin_event_loop_no_falla(status):
    s = starter(status, [])
    s.poke()   # fuera de un event loop (scripts): no revisa ni lanza
    assert s._task is None
