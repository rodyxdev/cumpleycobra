"""/evaluate con contrato y Gemini falsos: plazo, #9 (DeadlinePassed), #6 (NotFunded) y reintentos.

Estos caminos no se pueden provocar a voluntad en testnet; aquí se prueban sin red.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import gemini, main
from backend.hashing import rules_hash
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore
from backend.stellar_client import ContractError, ReleaseOutcome, StellarUnavailable

CLIENT = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
FREELANCER = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
AMOUNT = 10_000_000
NOW = 1_000_000
CODE = "def aplicar_descuento(precios, porcentaje):\n    return [round(p * (1 - porcentaje / 100), 2) for p in precios]\n"

APROBADO = {
    "trace": ["paso"], "logic": ["lógica"],
    "comparison": [f"✓ Criterio {i}: sí" for i in range(1, len(DEMO_SPEC["criteria"]) + 1)],
    "security_flags": [], "approved": True, "reason": "Cumple todos los criterios.",
}


class FakeChain:
    def __init__(self, deadline: int, release=None):
        self.now = NOW
        self.status = "Funded"
        self.onchain_freelancer = None
        self.deadline = deadline
        self._release = release
        self.release_calls = 0
        self.trustline = True
        self.last_release = None      # (code_hash, verdict_hash) del último release
        self.failed_txs = set()       # hashes que getTransaction no confirma como SUCCESS

    def transaction_succeeded(self, tx_hash):
        return tx_hash not in self.failed_txs

    def has_usdc_trustline(self, address):
        return self.trustline

    def ledger_time(self):
        return self.now

    def get_task(self, task_id):
        return {"task_id": task_id, "client": CLIENT, "amount": AMOUNT, "deadline": self.deadline,
                "rules_hash": rules_hash(DEMO_SPEC), "status": self.status,
                "freelancer": self.onchain_freelancer}

    def release(self, task_id, freelancer, ch, vh, on_signed):
        self.release_calls += 1
        self.last_release = (ch, vh)
        return self._release(self, on_signed)


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate_content(self, **_):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r})()


class FakeGemini:
    def __init__(self, responses):
        self.aio = type("A", (), {})()
        self.aio.models = FakeModels(responses)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "BACKOFF_SECS", (0, 0))

    def make(chain, responses=(json.dumps(APROBADO),)):
        main.app.state.store = StateStore(tmp_path / "state.json")
        main.app.state.chain = chain
        main.app.state.gemini = FakeGemini(responses)
        main.app.state.settings = type("S", (), {"gemini_model": "falso"})()
        client = TestClient(main.app)  # sin `with`: no corre el lifespan real
        r = client.post("/tasks", json={"client_address": CLIENT, **DEMO_SPEC,
                                        "amount": AMOUNT, "deadline_minutes": 10})
        task_id = r.json()["task_id"]
        invite = r.json()["invite_token"]
        ft = client.post(f"/tasks/{task_id}/accept",
                         json={"freelancer_address": FREELANCER, "invite_token": invite}).json()["freelancer_token"]

        def evaluate(code=CODE):
            return client.post("/evaluate", headers={"X-Freelancer-Token": ft},
                               json={"task_id": task_id, "freelancer_address": FREELANCER, "code": code})

        def used():
            return len(main.app.state.store.tasks[task_id]["submissions"])

        return evaluate, used, task_id

    return make


def ok_release(chain, on_signed):
    on_signed("aa" * 32)
    chain.status, chain.onchain_freelancer = "Released", FREELANCER
    return ReleaseOutcome("success", "aa" * 32)


def test_aprobado_y_pagado(api):
    evaluate, used, _ = api(FakeChain(NOW + 600, ok_release))
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] == "aa" * 32 and used() == 1


def test_deadline_passed_9_no_reintenta_y_responde_aprobado_sin_hash(api):
    def release(chain, on_signed):
        raise ContractError(9)
    chain = FakeChain(NOW + 600, release)
    evaluate, used, _ = api(chain)
    r = evaluate().json()
    assert r["approved"] is True
    assert r["transaction_hash"] is None
    assert "plazo" in r["reason"] and "manualmente" in r["reason"]
    assert chain.release_calls == 1
    # El reenvío es caché y no vuelve a intentar el release.
    r2 = evaluate().json()
    assert r2["stage"] == "cache" and chain.release_calls == 1 and used() == 1


def test_not_funded_6_con_tarea_released_para_el_programador_es_exito(api):
    # El primer intento firmó y envió, pero la confirmación se perdió; el reintento da #6.
    def release(chain, on_signed):
        if chain.release_calls == 1:
            on_signed("bb" * 32)
            chain.status, chain.onchain_freelancer = "Released", FREELANCER
            return ReleaseOutcome("failed", "bb" * 32, "sin confirmar")
        raise ContractError(6)
    evaluate, used, task_id = api(FakeChain(NOW + 600, release))
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] == "bb" * 32
    assert main.app.state.store.tasks[task_id]["release"]["status"] == "success"


def test_not_funded_6_sin_ser_released_no_es_exito(api):
    def release(chain, on_signed):
        chain.status = "Refunded"
        raise ContractError(6)
    evaluate, _, _ = api(FakeChain(NOW + 600, release))
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] is None
    assert "Refunded" in r["reason"]


def test_menos_de_120_s_rechaza_sin_contar(api):
    evaluate, used, _ = api(FakeChain(NOW + 119, ok_release))
    r = evaluate()
    assert r.status_code == 409 and r.json()["error"] == "DEADLINE_TOO_CLOSE" and used() == 0


def test_sin_tiempo_para_release_no_firma_ni_cuenta(api):
    chain = FakeChain(NOW + 130, ok_release)

    async def lento(**_):
        chain.now = NOW + 110  # Gemini tardó: quedan 20 s (< 30 s de presupuesto del release)
        return type("R", (), {"text": json.dumps(APROBADO)})()

    evaluate, used, _ = api(chain)
    main.app.state.gemini.aio.models.generate_content = lento
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] is None
    assert chain.release_calls == 0 and used() == 0


def test_antes_de_reintentar_gemini_revisa_el_plazo(api):
    chain = FakeChain(NOW + 130, ok_release)

    async def timeout(**_):
        chain.now = NOW + 90  # quedan 40 s: no alcanza para otro intento (20 s) + release (30 s)
        raise httpx.ReadTimeout("timeout")

    evaluate, used, _ = api(chain)
    main.app.state.gemini.aio.models.generate_content = timeout
    r = evaluate()
    assert r.status_code == 409 and r.json()["error"] == "DEADLINE_TOO_CLOSE" and used() == 0


def test_error_transitorio_se_reintenta(api):
    evaluate, used, _ = api(FakeChain(NOW + 600, ok_release),
                            [httpx.ReadTimeout("t"), json.dumps(APROBADO)])
    r = evaluate().json()
    assert r["approved"] is True and main.app.state.gemini.aio.models.calls == 2 and used() == 1


def test_fuera_de_esquema_dos_veces_es_engine_unavailable_sin_contar(api):
    evaluate, used, _ = api(FakeChain(NOW + 600, ok_release), ["no es json", '{"approved": true}'])
    r = evaluate()
    assert r.status_code == 502 and r.json()["error"] == "ENGINE_UNAVAILABLE" and used() == 0


def test_security_flags_fuerza_rechazo_aunque_gemini_apruebe(api):
    con_flag = {**APROBADO, "security_flags": ["instrucciones al evaluador en el docstring"]}
    chain = FakeChain(NOW + 600, ok_release)
    evaluate, _, _ = api(chain, [json.dumps(con_flag)])
    r = evaluate().json()
    assert r["approved"] is False and chain.release_calls == 0


def test_accept_sin_trustline_es_409_no_usdc_trustline(tmp_path):
    chain = FakeChain(NOW + 600, ok_release)
    chain.trustline = False
    main.app.state.store = StateStore(tmp_path / "state.json")
    main.app.state.chain = chain
    client = TestClient(main.app)
    r = client.post("/tasks", json={"client_address": CLIENT, **DEMO_SPEC,
                                    "amount": AMOUNT, "deadline_minutes": 10}).json()
    resp = client.post(f"/tasks/{r['task_id']}/accept",
                       json={"freelancer_address": FREELANCER, "invite_token": r["invite_token"]})
    assert resp.status_code == 409 and resp.json()["error"] == "NO_USDC_TRUSTLINE"
    assert main.app.state.store.tasks[r["task_id"]]["freelancer_address"] is None


@pytest.mark.parametrize("falla", [ContractError(13), StellarUnavailable("red")])
def test_release_sin_trustline_no_es_reintentable(api, falla):
    def release(chain, on_signed):
        chain.trustline = False  # la quitó después de aceptar
        raise falla
    chain = FakeChain(NOW + 600, release)
    evaluate, _, task_id = api(chain)
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] is None
    assert "trustline" in r["reason"]
    cached = main.app.state.store.tasks[task_id]["cache"][r["code_hash"]]
    assert cached["payment_retryable"] is False
    # El reenvío es caché y no reintenta el release.
    assert evaluate().json()["stage"] == "cache" and chain.release_calls == 1


def test_release_por_red_con_trustline_si_es_reintentable(api):
    def release(chain, on_signed):
        if chain.release_calls == 1:
            raise StellarUnavailable("red")
        return ok_release(chain, on_signed)
    chain = FakeChain(NOW + 600, release)
    evaluate, used, _ = api(chain)
    r = evaluate().json()
    assert r["transaction_hash"] is None and "red" in r["reason"]
    r2 = evaluate().json()
    assert r2["stage"] == "cache" and r2["transaction_hash"] == "aa" * 32 and used() == 1


def test_verdicts_del_cliente_sin_trace_logic_ni_codigo(api):
    evaluate, _, task_id = api(FakeChain(NOW + 600, ok_release))
    evaluate()
    client = TestClient(main.app)
    ct = main.app.state.store.tasks[task_id]["client_token"]
    assert client.get(f"/tasks/{task_id}/verdicts").status_code == 403
    body = client.get(f"/tasks/{task_id}/verdicts", headers={"X-Client-Token": ct}).json()
    v = body["verdicts"][0]
    assert set(v) == {"code_hash", "approved", "stage", "reason", "comparison", "transaction_hash", "video_url", "consented"}
    texto = json.dumps(body, ensure_ascii=False)
    assert "paso" not in texto and "lógica" not in texto and "aplicar_descuento(precios" not in texto


def test_demo_expone_plantilla_y_casos():
    body = TestClient(main.app).get("/demo").json()
    assert body["spec"] == DEMO_SPEC
    assert [c["id"] for c in body["casos"]] == ["A", "B", "C", "D"]
    assert [c["principal"] for c in body["casos"]] == [True, True, True, False]
