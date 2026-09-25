"""Reputación verificable: calificación del cliente, listado y perfil del programador."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from stellar_sdk import Keypair, scval

from backend import identidad, main, reputacion
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore
from backend.stellar_client import StellarUnavailable

P1 = "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ"
P2 = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
C1 = "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL"
C2 = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
AMOUNT = 11_350_674
SECRET_CODE = "def aplicar_descuento(p, x):\n    return 'CODIGO-PRIVADO-DEL-PROGRAMADOR'\n"


class MultiChain:
    """Contrato falso con una tarea on-chain por task_id."""

    def __init__(self):
        self.onchain: dict[str, dict] = {}
        self.get_task_calls = 0
        self.down = False

    def has_usdc_trustline(self, address):
        return True

    def ledger_time(self):
        return 1_000_000

    def get_task(self, task_id):
        self.get_task_calls += 1
        if self.down:
            raise StellarUnavailable("RPC caído")
        return self.onchain.get(task_id)


class FakeEvents:
    def __init__(self, by_task=None, fail=False):
        self.by_task, self.fail = by_task or {}, fail

    def refresh(self):
        if self.fail:
            raise RuntimeError("getEvents no respondió")
        return dict(self.by_task)


@pytest.fixture
def world(tmp_path, monkeypatch):
    # Llaves de prueba para las sesiones SEP-10 (calificar exige la del cliente on-chain).
    monkeypatch.setenv("SEP10_SIGNING_SECRET", Keypair.random().secret)
    monkeypatch.setenv("SESSION_SECRET", "secreto-de-prueba")
    chain = MultiChain()
    main.app.state.store = StateStore(tmp_path / "state.json")
    main.app.state.chain = chain
    main.app.state.payment_events = FakeEvents()
    main.app.state.settings = SimpleNamespace(gemini_model="falso", contract_id="C")
    client = TestClient(main.app)

    def task(freelancer, client_address=C1, status="Released", engine=True, description=None):
        spec = {**DEMO_SPEC, "description": description or DEMO_SPEC["description"]}
        r = client.post("/tasks", json={"client_address": client_address, **spec,
                                        "amount": AMOUNT, "deadline_minutes": 10}).json()
        tid = r["task_id"]
        client.post(f"/tasks/{tid}/accept", json={"freelancer_address": freelancer, "invite_token": r["invite_token"]})
        t = main.store().tasks[tid]
        ch = "c9" * 32
        t["codes"][ch] = {"code": SECRET_CODE, "video_url": None, "code_hash": ch, "approved": True}
        t["submissions"].append({"code_hash": ch, "stage": "llm", "approved": True, "at": 1_790_300_000})
        if engine:
            t["release"] = {"status": "success", "transaction_hash": "ab" * 32, "freelancer": freelancer,
                            "code_hash": ch, "verdict_hash": "cd" * 32}
        main.store().save()
        if status:
            chain.onchain[tid] = {"task_id": tid, "client": client_address, "amount": AMOUNT, "deadline": 2_000_000,
                                  "rules_hash": r["rules_hash"], "status": status,
                                  "freelancer": freelancer if status == "Released" else None}
        return tid, r["client_token"]

    yield SimpleNamespace(chain=chain, client=client, task=task)
    del main.app.state.payment_events


def session(address):
    return {"Authorization": "Bearer " + identidad.issue_session(main.auth_keys(), address)["token"]}


def rate(world, tid, token, as_client=C1, **body):
    headers = {**({"X-Client-Token": token} if token else {}), **session(as_client)}
    return world.client.post(f"/tasks/{tid}/calificacion", headers=headers, json=body or {"estrellas": 5})


# --- POST /tasks/{id}/calificacion --------------------------------------------------------------
def test_calificacion_token_tarea_no_pagada_y_doble(world):
    tid, token = world.task(P1)
    assert rate(world, tid, "token-equivocado").json()["error"] == "INVALID_TOKEN"
    assert rate(world, tid, None).status_code == 403

    funded, ftoken = world.task(P1, status="Funded", engine=False)
    r = rate(world, funded, ftoken)
    assert r.status_code == 409 and r.json()["error"] == "TASK_NOT_RELEASED"
    never, ntoken = world.task(P1, status=None, engine=False)  # sin depósito
    assert rate(world, never, ntoken).json()["error"] == "TASK_NOT_RELEASED"

    ok = rate(world, tid, token, estrellas=4, comentario="  Entregó a tiempo.  ")
    assert ok.status_code == 200 and ok.json() == {"task_id": tid, "estrellas": 4, "comentario": "Entregó a tiempo."}
    again = rate(world, tid, token, estrellas=1)
    assert again.status_code == 409 and again.json()["error"] == "ALREADY_RATED"
    assert main.store().tasks[tid]["rating"]["estrellas"] == 4  # no se sobrescribe
    # Persistida en state.json y visible en la vista pública de la tarea.
    assert StateStore(main.store().path).tasks[tid]["rating"]["comentario"] == "Entregó a tiempo."
    assert world.client.get(f"/tasks/{tid}").json()["rating"]["estrellas"] == 4


@pytest.mark.parametrize("body", [
    {"estrellas": 0}, {"estrellas": 6}, {"estrellas": 4.5}, {"estrellas": "5"}, {"estrellas": True},
    {}, {"estrellas": 5, "comentario": "x" * 281}, {"estrellas": 5, "extra": 1}, {"estrellas": 5, "comentario": 3},
])
def test_calificacion_limites_invalidos(world, body):
    tid, token = world.task(P1)
    r = world.client.post(f"/tasks/{tid}/calificacion", headers={"X-Client-Token": token}, json=body)
    assert r.status_code == 400 and r.json()["error"] == "INVALID_REQUEST"
    assert "rating" not in main.store().tasks[tid]


def test_calificacion_limites_validos_y_tarea_inexistente(world):
    for stars in (1, 5):
        tid, token = world.task(P1)
        assert rate(world, tid, token, estrellas=stars, comentario="x" * 280).status_code == 200
    tid, token = world.task(P1)
    assert rate(world, tid, token, estrellas=3, comentario="   ").json()["comentario"] is None
    assert rate(world, "no-existe", token).json()["error"] == "TASK_NOT_FOUND"


# --- GET /programadores y GET /programadores/{address} ------------------------------------------
def test_listado_y_perfil_con_metricas_y_confirmacion_on_chain(world):
    a, ta = world.task(P1, C1)                                      # motor (evento)
    b, _ = world.task(P1, C2, engine=False)                         # manual (evento)
    c, tc = world.task(P1, C1)                                      # motor, sin evento: se toma de state.json
    world.task(P1, C2, status="Funded")                             # state dice release, la cadena no: no cuenta
    d, td = world.task(P2, C1, engine=False)                        # manual sin evento: sin hash
    world.task(P2, status=None, engine=False)                       # nunca depositada
    main.app.state.payment_events = FakeEvents({
        a: {"paid_by": "motor", "transaction_hash": "e1" * 32, "paid_at": "2026-09-25T15:04:26Z"},
        b: {"paid_by": "manual", "transaction_hash": "e2" * 32, "paid_at": "2026-09-24T20:43:17Z"},
    })
    rate(world, a, ta, estrellas=5)
    rate(world, c, tc, estrellas=4, comentario="Bien")
    rate(world, d, td, estrellas=2)

    listing = world.client.get("/programadores").json()["programmers"]
    assert [p["address"] for p in listing] == [P1, P2]  # ordenados por pagadas por el motor
    assert listing[0] == {"address": P1, "engine_paid": 2, "manual_paid": 1, "distinct_clients": 2,
                          "rating_average": 4.5, "rating_count": 2}
    assert listing[1] == {"address": P2, "engine_paid": 0, "manual_paid": 1, "distinct_clients": 1,
                          "rating_average": 2.0, "rating_count": 1}

    prof = world.client.get(f"/programadores/{P1}").json()
    assert {k: prof[k] for k in listing[0]} == listing[0]
    hist = {h["task_id"]: h for h in prof["history"]}
    assert set(hist) == {a, b, c}
    assert hist[a]["paid_by"] == "motor" and hist[a]["transaction_hash"] == "e1" * 32
    assert hist[b]["paid_by"] == "manual" and hist[b]["transaction_hash"] == "e2" * 32
    assert hist[c]["paid_by"] == "motor" and hist[c]["transaction_hash"] == "ab" * 32
    assert hist[c]["paid_at"] == datetime.fromtimestamp(1_790_300_000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert hist[a]["rating"] == {"estrellas": 5, "comentario": None}
    assert hist[a]["criteria_count"] == len(DEMO_SPEC["criteria"]) and hist[a]["amount"] == AMOUNT
    assert set(hist[a]) == {"task_id", "description", "criteria_count", "amount", "paid_by",
                            "transaction_hash", "paid_at", "rating"}
    assert [h["task_id"] for h in prof["history"]][0] == a  # el más reciente primero
    assert world.client.get(f"/programadores/{P2}").json()["history"][0]["transaction_hash"] is None


def test_perfil_nunca_expone_codigo_tokens_ni_analisis(world):
    tid, token = world.task(P1, description="Una descripción " + "larga " * 60)
    task = main.store().tasks[tid]
    rate(world, tid, token, estrellas=5, comentario="Excelente")
    raw = world.client.get(f"/programadores/{P1}").text + world.client.get("/programadores").text
    for secret in (task["client_token"], task["invite_token"], task["freelancer_token"], "CODIGO-PRIVADO", C1):
        assert secret not in raw
    data = json.loads(world.client.get(f"/programadores/{P1}").text)
    keys = {k for h in data["history"] for k in h} | set(data)
    assert not {"code", "trace", "logic", "analysis", "client", "client_token", "freelancer_token",
                "invite_token", "comparison", "reason"} & keys
    assert len(data["history"][0]["description"]) <= reputacion.DESCRIPTION_MAX


def test_perfil_direccion_invalida_y_sin_tareas(world):
    assert world.client.get("/programadores/no-es-direccion").json()["error"] == "INVALID_REQUEST"
    empty = world.client.get(f"/programadores/{P2}").json()
    assert empty["history"] == [] and empty["engine_paid"] == 0 and empty["rating_average"] is None
    assert world.client.get("/programadores").json() == {"programmers": []}


def test_rpc_caido_es_502_y_eventos_caidos_usan_state(world):
    tid, _ = world.task(P1)
    b, _ = world.task(P1, engine=False)
    main.app.state.payment_events = FakeEvents(fail=True)
    prof = world.client.get(f"/programadores/{P1}").json()
    hist = {h["task_id"]: h for h in prof["history"]}
    assert hist[tid]["paid_by"] == "motor" and hist[tid]["transaction_hash"] == "ab" * 32
    assert hist[b]["paid_by"] == "manual" and hist[b]["transaction_hash"] is None

    reputacion.onchain_cache(world.chain).clear()
    world.chain.down = True
    r = world.client.get("/programadores")
    assert r.status_code == 502 and r.json()["error"] == "CHAIN_UNAVAILABLE"


def test_released_se_cachea_y_lo_demas_se_vuelve_a_leer(world):
    world.task(P1)
    world.task(P1, status="Funded")
    world.client.get("/programadores")
    first = world.chain.get_task_calls
    world.client.get("/programadores")
    assert world.chain.get_task_calls == first  # dentro del TTL, nada se vuelve a leer
    for tid, (onchain, expires) in reputacion.onchain_cache(world.chain).items():
        assert (expires is None) == (onchain["status"] == "Released")


# --- PaymentEvents: getEvents con cursor ---------------------------------------------------------
def _event(topic, task_id, tx, ok=True):
    return SimpleNamespace(topic=[scval.to_symbol(topic).to_xdr(), scval.to_string(task_id).to_xdr()],
                           transaction_hash=tx, ledger_close_at=datetime(2026, 9, 25, 15, 4, 26, tzinfo=timezone.utc),
                           in_successful_contract_call=ok)


class FakeServer:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get_health(self):
        return SimpleNamespace(oldest_ledger=100)

    def get_events(self, start_ledger=None, filters=None, cursor=None, limit=None):
        self.calls.append((start_ledger, cursor))
        i = min(len(self.calls) - 1, len(self.pages) - 1)
        events, next_cursor = self.pages[i]
        return SimpleNamespace(events=events, cursor=next_cursor)


def test_eventos_de_pago_pagina_con_cursor_y_clasifica():
    server = FakeServer([
        ([_event("release", "T1", "aa" * 32)], "c1"),
        ([], "c2"),                                   # ventana sin eventos: el cursor avanza
        ([_event("client_release", "T2", "bb" * 32), _event("release", "T3", "cc" * 32, ok=False)], "c3"),
        ([], "c3"),                                   # sin eventos y sin avance: fin
    ])
    ev = reputacion.PaymentEvents(server, "C")
    got = ev.refresh()
    assert got == {"T1": {"paid_by": "motor", "transaction_hash": "aa" * 32, "paid_at": "2026-09-25T15:04:26Z"},
                   "T2": {"paid_by": "manual", "transaction_hash": "bb" * 32, "paid_at": "2026-09-25T15:04:26Z"}}
    assert server.calls[0] == (101, None) and ev.cursor == "c3"
    # La siguiente consulta sigue desde el cursor, no desde el ledger más viejo.
    server.pages, server.calls = [([], "c3")], []
    ev.refresh()
    assert server.calls == [(None, "c3")]
