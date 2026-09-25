"""Correcciones P1 de la auditoría: cada test reproduce el escenario reportado."""

import json

import httpx
from fastapi.testclient import TestClient

from backend import main
from backend.deterministic import analyze
from backend.stellar_client import ReleaseOutcome, StellarUnavailable
from backend.tests.test_evaluate_pagos import (  # noqa: F401
    APROBADO, CODE, FREELANCER, NOW, FakeChain, api, ok_release,
)
from scripts.verificar_pago import recompute_verdict_hash, select_verdict

VIDEO = "https://drive.google.com/file/d/1jg-nMazcC4Cln9eSSia5be0RsHSFizM9/view?usp=sharing"
CANONICAL = "https://drive.google.com/file/d/1jg-nMazcC4Cln9eSSia5be0RsHSFizM9/preview"
OTRO = CODE.replace("precios]", "precios]  # otra entrega").replace("# otra entrega", "") + "\n"


def post(task_id, code=CODE, video=None):
    task = main.store().tasks[task_id]
    return TestClient(main.app).post("/evaluate", headers={"X-Freelancer-Token": task["freelancer_token"]},
                                     json={"task_id": task_id, "freelancer_address": FREELANCER,
                                           "code": code, "video_url": video})


# --- 1. video_url en /evaluate y verificación con /evaluate o /verdicts -----------------------
def test_evaluate_devuelve_video_url_y_el_hash_se_recalcula_desde_evaluate_y_verdicts(api):
    chain = FakeChain(NOW + 600, ok_release)
    _, _, task_id = api(chain)
    r = post(task_id, video=VIDEO).json()
    assert r["video_url"] == CANONICAL and r["approved"] and r["transaction_hash"]
    on_chain_vh = chain.last_release[1]

    # Respuesta de /evaluate.
    v, tid, _ = select_verdict(r, r["code_hash"])
    assert recompute_verdict_hash(v, tid) == r["verdict_hash"] == on_chain_vh

    # Respuesta completa de /verdicts y un elemento suelto con el task_id aparte.
    task = main.store().tasks[task_id]
    listing = TestClient(main.app).get(f"/tasks/{task_id}/verdicts",
                                       headers={"X-Client-Token": task["client_token"]}).json()
    v, tid, _ = select_verdict(listing, r["code_hash"])
    assert recompute_verdict_hash(v, tid) == on_chain_vh
    v, tid, _ = select_verdict(listing["verdicts"][0], r["code_hash"], task_id)
    assert recompute_verdict_hash(v, tid) == on_chain_vh

    # Reenvío en caché (stage «cache»): el verificador usa el stage original.
    cached = post(task_id, video=VIDEO).json()
    assert cached["stage"] == "cache" and cached["video_url"] == CANONICAL
    v, tid, notes = select_verdict(cached, cached["code_hash"])
    assert recompute_verdict_hash(v, tid) == on_chain_vh and notes


def test_evaluate_sin_video_devuelve_video_url_null(api):
    _, _, task_id = api(FakeChain(NOW + 600, ok_release))
    assert post(task_id).json()["video_url"] is None


# --- 2. Sin reloj del ledger: error de red, nunca «no queda plazo» ---------------------------
class ClockFailsAfter(FakeChain):
    """El reloj responde en las guardias y deja de responder después."""
    def __init__(self, deadline, release, ok_calls):
        super().__init__(deadline, release)
        self.ok_calls = ok_calls
        self.clock_calls = 0

    def ledger_time(self):
        self.clock_calls += 1
        if self.clock_calls > self.ok_calls:
            raise StellarUnavailable("sin reloj")
        return self.now


def test_sin_reloj_antes_del_release_es_error_de_red_reintentable(api):
    chain = ClockFailsAfter(NOW + 600, ok_release, ok_calls=1)  # 1 = la guardia de /evaluate
    evaluate, used, task_id = api(chain)
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] is None
    assert "problema de red" in r["reason"] and main.REASON_NO_TIME_TO_RELEASE not in r["reason"]
    assert main.store().tasks[task_id]["cache"][r["code_hash"]]["payment_retryable"] is True
    assert chain.release_calls == 0
    # Con el reloj de vuelta, el reenvío del mismo código paga sin contar otro envío.
    chain.ok_calls = 10**6
    r2 = evaluate().json()
    assert r2["transaction_hash"] == "aa" * 32 and used() == 1


def test_sin_reloj_antes_de_reintentar_gemini_es_error_de_red(api):
    chain = ClockFailsAfter(NOW + 600, ok_release, ok_calls=1)
    evaluate, used, _ = api(chain, responses=(httpx.ReadTimeout("lento"), json.dumps(APROBADO)))
    r = evaluate()
    assert r.status_code == 502 and r.json()["error"] == "CHAIN_UNAVAILABLE"
    assert "reloj" in r.json()["message"] and used() == 0


# --- 3. open con argumentos no verificables --------------------------------------------------
def test_open_con_starred_o_kwargs_se_rechaza():
    for code in ("args = ['x.txt', 'w']\nopen(*args)\n", "kw = {'mode': 'w'}\nopen('x.txt', **kw)\n"):
        det = analyze(code, [])
        assert not det.ok and det.security
        assert any("open con argumentos no verificables" in p for p in det.problems)


# --- 4. ImportFrom revisa cada nombre; subprocess y socket prohibidos siempre -----------------
def test_from_os_import_system_environ_con_os_permitido_se_rechaza():
    det = analyze("from os import system, environ\nsystem('ls')\n", ["os"])
    assert not det.ok
    assert any("'system'" in p for p in det.problems) and any("'environ'" in p for p in det.problems)


def test_subprocess_y_socket_se_rechazan_aunque_esten_permitidos():
    for code, deps in (("from subprocess import run\n", []), ("from subprocess import run\n", ["subprocess"]),
                       ("import socket\n", ["socket"]), ("from os import *\n", ["os"])):
        det = analyze(code, deps)
        assert not det.ok, code


# --- 5. settle_not_funded solo acepta el release de esta entrega y SUCCESS -------------------
def test_escenario_a_pagada_por_aprobacion_manual_no_se_atribuye_el_release_fallido(api):
    # El release firmado quedó FAILED y el cliente pagó con client_release al mismo programador.
    def release(chain, on_signed):
        on_signed("ee" * 32)
        chain.failed_txs.add("ee" * 32)
        chain.status, chain.onchain_freelancer = "Released", FREELANCER
        return ReleaseOutcome("failed", "ee" * 32, "la transacción quedó FAILED")
    evaluate, _, _ = api(FakeChain(NOW + 600, release))
    r = evaluate().json()
    assert r["approved"] is True and r["transaction_hash"] is None
    assert main.REASON_PAID_OTHERWISE in r["reason"]


def test_escenario_b_pagada_por_otra_entrega_no_se_atribuye_su_hash(api):
    # X: aprobada, el release se firmó pero la red cayó antes de confirmar (reintentable).
    # Y: aprobada después, su release sí pagó. El reintento de X no debe reportar el hash de Y.
    def release(chain, on_signed):
        if chain.release_calls == 1:
            on_signed("cc" * 32)
            chain.failed_txs.add("cc" * 32)
            raise StellarUnavailable("red")
        on_signed("dd" * 32)
        chain.status, chain.onchain_freelancer = "Released", FREELANCER
        return ReleaseOutcome("success", "dd" * 32)
    evaluate, _, task_id = api(FakeChain(NOW + 600, release),
                               responses=(json.dumps(APROBADO), json.dumps(APROBADO)))
    x = evaluate().json()
    assert x["transaction_hash"] is None and "problema de red" in x["reason"]
    y = evaluate(OTRO).json()
    assert y["transaction_hash"] == "dd" * 32
    x2 = evaluate().json()
    assert x2["stage"] == "cache" and x2["transaction_hash"] is None
    assert main.REASON_PAID_OTHERWISE in x2["reason"]


def test_release_propio_confirmado_sigue_siendo_exito(api):
    # El caso legítimo: #6 porque el primer release sí llegó, y es de esta misma entrega.
    def release(chain, on_signed):
        if chain.release_calls == 1:
            on_signed("bb" * 32)
            chain.status, chain.onchain_freelancer = "Released", FREELANCER
            return ReleaseOutcome("failed", "bb" * 32, "sin confirmar")
        raise AssertionError("no debe reintentar")
    evaluate, _, _ = api(FakeChain(NOW + 600, release))
    assert evaluate().json()["transaction_hash"] == "bb" * 32
