"""Cuotas solo en Gemini, aislamiento entre usos, IP del proxy y respuestas con CORS."""
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import main
from backend.limites import MSG_PER_IP, RateLimited, RateLimiter, client_ip
from backend.plantilla import DEMO_RAW_REQUEST, DEMO_SPEC
from backend.tests.test_drafting import setup  # noqa: F401
from backend.tests.test_evaluate_pagos import APROBADO, CODE, NOW, FakeChain, api  # noqa: F401

DAY0 = 1_790_000_000
REJECTED = {**APROBADO, "approved": False, "reason": "Rechazo de prueba"}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_por_ip_ventana_deslizante_y_limpieza():
    clock = Clock(DAY0)
    rl = RateLimiter(clock)
    assert rl.check_ip("a", 2) is None
    assert rl.check_ip("a", 2) is None
    refused = rl.check_ip("a", 2)
    assert str(refused) == MSG_PER_IP and 1 <= refused.retry_after <= 61
    assert rl.check_ip("b", 2) is None
    clock.t += 61
    assert rl.check_ip("c", 2) is None
    assert set(rl.hits) == {("gemini", "c")}
    assert rl.day_count == {"borrador": 0, "motor": 0}


def test_cuotas_independientes_y_cambio_de_dia(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    clock = Clock(DAY0)
    rl = RateLimiter(clock)
    rl.consume_daily("motor")
    with pytest.raises(RateLimited):
        rl.consume_daily("motor")
    rl.consume_daily("borrador")
    assert rl.day_count == {"borrador": 1, "motor": 1}
    clock.t = (DAY0 // 86400 + 1) * 86400 + 5
    rl.consume_daily("motor")
    assert rl.day_count == {"borrador": 0, "motor": 1}


def test_limite_especifico_prevalece_sobre_respaldo(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    monkeypatch.setenv("RATE_LIMIT_DAILY_BORRADOR", "2")
    monkeypatch.setenv("RATE_LIMIT_DAILY_MOTOR", "0")
    rl = RateLimiter()
    for _ in range(2):
        rl.consume_daily("borrador")
    with pytest.raises(RateLimited):
        rl.consume_daily("borrador")
    for _ in range(10):
        rl.consume_daily("motor")  # desactivación explícita
    assert rl.day_count["motor"] == 0


def test_cuota_diaria_atomica_entre_llamadas_concurrentes(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY", "3")
    rl = RateLimiter()
    def consume(_):
        try:
            rl.consume_daily("motor")
            return True
        except RateLimited:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(20))) == 3


def test_sin_limites_no_guarda_contadores():
    rl = RateLimiter()
    for _ in range(100):
        assert rl.check_ip("a", 0) is None
        rl.consume_daily("motor")
    assert not rl.hits and sum(rl.day_count.values()) == 0


def test_ip_usa_ultima_entrada_del_proxy_o_cliente():
    def req(value=None):
        return Request({"type": "http", "headers": [(b"x-forwarded-for", value.encode())] if value else [],
                        "client": ("192.0.2.10", 1000)})
    assert client_ip(req()) == "192.0.2.10"
    for prefix in ("1.1.1.1", "8.8.8.8, 9.9.9.9", "falsa"):
        assert client_ip(req(prefix + ", 198.51.100.20")) == "198.51.100.20"


@pytest.mark.parametrize("path", ["/tasks/draft", "/tasks/draft/review", "/evaluate"])
def test_429_por_ip_con_cors_y_sin_cuota(monkeypatch, path):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    client = TestClient(main.app)
    origin = main.frontend_origins(main.settings_for_cors.frontend_origin)[0]
    for i in range(2):
        assert client.post(path, json={}, headers={"X-Forwarded-For": f"192.0.2.{i}, 198.51.100.20"}).status_code == 400
    r = client.post(path, json={}, headers={"Origin": origin, "X-Forwarded-For": "192.0.2.99, 198.51.100.20"})
    assert r.status_code == 429 and r.json()["error"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["access-control-allow-origin"] == origin
    assert sum(main.rate_limiter.day_count.values()) == 0
    assert client.get("/health").status_code == 200
    assert client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": "POST"}).status_code == 200


@pytest.mark.parametrize("path,valid,reply", [
    ("/tasks/draft", {"raw_request": DEMO_RAW_REQUEST}, DEMO_SPEC),
    ("/tasks/draft/review", {"criteria": ["Devuelve una lista"]},
     {"criteria": [{"index": 0, "vague": False, "suggestion": None}]}),
])
def test_30_invalidas_no_consumen_cuota_y_una_valida_funciona(setup, monkeypatch, path, valid, reply):
    client, responses, calls = setup
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    for _ in range(30):
        assert client.post(path, json={}).status_code == 400
    assert not calls and sum(main.rate_limiter.day_count.values()) == 0
    responses.append(reply)
    assert client.post(path, json=valid).status_code == 200
    assert len(calls) == 1 and main.rate_limiter.day_count["borrador"] == 1


@pytest.mark.parametrize("first", ["motor", "borrador"])
def test_agotar_un_grupo_no_bloquea_otro_y_no_cuenta_envios(api, monkeypatch, first):
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    responses = [REJECTED, DEMO_SPEC] if first == "motor" else [DEMO_SPEC, REJECTED]
    evaluate, used, tid = api(FakeChain(NOW + 600), responses=map(json.dumps, responses))
    client = TestClient(main.app)
    draft = lambda: client.post("/tasks/draft", json={"raw_request": DEMO_RAW_REQUEST})
    review = lambda: client.post("/tasks/draft/review", json={"criteria": ["Devuelve una lista"]})
    if first == "motor":
        assert evaluate().status_code == 200
        for _ in range(3):
            assert evaluate(CODE + "\n").status_code == 429
        assert used() == 1
        assert draft().status_code == 200
    else:
        assert draft().status_code == 200
        assert review().status_code == 429
        assert used() == 0
        assert evaluate().status_code == 200
    assert review().status_code == 429
    assert evaluate(CODE + "\n").status_code == 429
    assert used() == 1
    assert evaluate().json()["stage"] == "cache"  # incluso agotada la cuota
    assert main.app.state.gemini.aio.models.calls == 2
    assert len(main.store().tasks[tid]["cache"]) == 1


def test_cuota_agotada_conserva_los_tres_envios_y_tiene_cors(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY_MOTOR", "1")
    evaluate, used, _ = api(FakeChain(NOW + 600))
    main.rate_limiter.consume_daily("motor")
    for _ in range(3):
        r = evaluate()
        assert r.status_code == 429 and r.json()["error"] == "RATE_LIMITED"
    assert used() == 0 and main.app.state.gemini.aio.models.calls == 0
    client = TestClient(main.app)
    monkeypatch.setenv("RATE_LIMIT_DAILY_BORRADOR", "1")
    main.rate_limiter.consume_daily("borrador")
    origin = main.frontend_origins(main.settings_for_cors.frontend_origin)[0]
    r = client.post("/tasks/draft", json={"raw_request": DEMO_RAW_REQUEST}, headers={"Origin": origin})
    assert r.status_code == 429 and r.headers["access-control-allow-origin"] == origin
    assert int(r.headers["Retry-After"]) > 0


def test_guardias_y_rechazo_determinista_no_gastan_cuota(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    evaluate, used, _ = api(FakeChain(NOW + 100))
    assert evaluate().status_code == 409
    main.app.state.chain.deadline = NOW + 600
    r = evaluate("import os\nx = os.environ")
    assert r.status_code == 200 and r.json()["stage"] == "deterministic"
    assert used() == 1 and main.app.state.gemini.aio.models.calls == 0
    assert sum(main.rate_limiter.day_count.values()) == 0


def test_reintento_agotado_no_se_convierte_en_502_ni_cuenta_envio(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY_MOTOR", "1")
    evaluate, used, _ = api(FakeChain(NOW + 600), responses=[httpx.ReadTimeout("prueba")])
    assert evaluate().status_code == 429
    assert used() == 0 and main.app.state.gemini.aio.models.calls == 1
