"""Límite de peticiones a /tasks/draft, /tasks/draft/review y /evaluate."""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.limites import MSG_DAILY, MSG_PER_IP, RateLimiter

DAY0 = 1_790_000_000  # un instante cualquiera; el día UTC se calcula a partir de aquí


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


# --- Unidad ---------------------------------------------------------------------------------------
def test_por_ip_con_ventana_deslizante():
    clock = Clock(DAY0)
    rl = RateLimiter(clock)
    assert rl.check("1.1.1.1", 2, 0) is None
    assert rl.check("1.1.1.1", 2, 0) is None
    refused = rl.check("1.1.1.1", 2, 0)
    assert refused[0] == MSG_PER_IP and 1 <= refused[1] <= 61
    assert rl.check("2.2.2.2", 2, 0) is None          # otra IP no se ve afectada
    clock.t += 61
    assert rl.check("1.1.1.1", 2, 0) is None          # la ventana se movió


def test_tope_diario_global_y_cambio_de_dia():
    clock = Clock(DAY0)
    rl = RateLimiter(clock)
    for ip in ("a", "b", "c"):
        assert rl.check(ip, 0, 3) is None
    refused = rl.check("d", 0, 3)                      # otra IP, pero el tope es global
    assert refused[0] == MSG_DAILY and refused[1] > 0
    clock.t = (DAY0 // 86400 + 1) * 86400 + 5         # día UTC siguiente
    assert rl.check("d", 0, 3) is None


def test_desactivado_por_defecto():
    rl = RateLimiter(Clock(DAY0))
    assert all(rl.check("1.1.1.1", 0, 0) is None for _ in range(100))


def test_un_rechazo_no_consume_cupo():
    clock = Clock(DAY0)
    rl = RateLimiter(clock)
    rl.check("a", 1, 10)
    for _ in range(5):
        assert rl.check("a", 1, 10) is not None
    assert rl.day_count == 1


# --- Integración con la app -----------------------------------------------------------------------
@pytest.fixture
def limited(monkeypatch):
    main.rate_limiter.hits.clear()
    main.rate_limiter.day, main.rate_limiter.day_count = None, 0
    yield TestClient(main.app)
    main.rate_limiter.hits.clear()
    main.rate_limiter.day, main.rate_limiter.day_count = None, 0


@pytest.mark.parametrize("path", ["/tasks/draft", "/tasks/draft/review", "/evaluate"])
def test_429_rate_limited_con_mensaje_y_cors(limited, monkeypatch, path):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.delenv("RATE_LIMIT_DAILY", raising=False)
    origin = main.frontend_origins(main.settings_for_cors.frontend_origin)[0]
    for _ in range(2):
        assert limited.post(path, json={}).status_code == 400   # cuerpo inválido, pero cuenta
    r = limited.post(path, json={}, headers={"Origin": origin})
    assert r.status_code == 429
    assert r.json() == {"error": "RATE_LIMITED", "message": MSG_PER_IP}
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["access-control-allow-origin"] == origin   # el navegador puede leer el mensaje


def test_solo_limita_las_rutas_del_motor(limited, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    limited.post("/tasks/draft", json={})
    assert limited.post("/tasks/draft", json={}).status_code == 429
    assert limited.get("/health").status_code == 200
    assert limited.post("/tasks", json={}).status_code == 400          # crear tarea no se limita
    assert limited.options("/evaluate", headers={"Origin": "http://localhost:3000",
                                                  "Access-Control-Request-Method": "POST"}).status_code == 200


def test_sin_variables_no_hay_limite(limited, monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("RATE_LIMIT_DAILY", raising=False)
    assert all(limited.post("/tasks/draft", json={}).status_code == 400 for _ in range(25))


def test_valor_mal_escrito_queda_desactivado(limited, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "diez")
    assert all(limited.post("/evaluate", json={}).status_code == 400 for _ in range(15))
