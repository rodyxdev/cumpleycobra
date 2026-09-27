"""Escrituras públicas, documentación optativa y configuración de identidad segura."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.config import api_docs_options
from backend.tests.test_reputacion import C1, world  # noqa: F401

WRITES = [("POST", "/tasks"), ("POST", "/propuestas"), ("GET", "/auth/challenge"),
          ("POST", "/auth/token"), ("PUT", "/perfil"), ("POST", "/tasks/ficticia/calificacion")]


@pytest.mark.parametrize("method,path", WRITES)
def test_escrituras_limitadas_por_ip_sin_cuota_diaria(monkeypatch, method, path):
    monkeypatch.setenv("RATE_LIMIT_WRITES_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_DAILY", "1")
    client = TestClient(main.app)
    origin = main.frontend_origins(main.settings_for_cors.frontend_origin)[0]
    for i in range(2):
        assert client.request(method, path, json={}, headers={"X-Real-IP": "198.51.100.10", "X-Forwarded-For": f"192.0.2.{i}, 203.0.113.{i}"}).status_code != 429
    r = client.request(method, path, json={}, headers={"Origin": origin, "X-Real-IP": "198.51.100.10", "X-Forwarded-For": "192.0.2.99, 203.0.113.99"})
    assert r.status_code == 429 and r.json()["error"] == "RATE_LIMITED"
    assert r.headers["access-control-allow-origin"] == origin
    assert int(r.headers["Retry-After"]) > 0
    assert client.request(method, path, json={}, headers={"X-Real-IP": "198.51.100.11"}).status_code != 429
    assert sum(main.rate_limiter.day_count.values()) == 0


def test_escrituras_comparten_30_por_defecto_y_no_bloquean_motor():
    client = TestClient(main.app)
    for i in range(30):
        method, path = WRITES[i % len(WRITES)]
        assert client.request(method, path, json={}).status_code != 429
    assert client.post("/tasks", json={}).status_code == 429
    assert client.post("/tasks/draft", json={}).status_code == 400
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("enabled", [None, "false", "true"])
def test_documentacion_solo_si_se_habilita(monkeypatch, enabled):
    if enabled is None:
        monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    else:
        monkeypatch.setenv("ENABLE_API_DOCS", enabled)
    client = TestClient(FastAPI(**api_docs_options()))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == (200 if enabled == "true" else 404)


@pytest.mark.parametrize("secret", ["", "ficticio", "x" * 31])
def test_session_corta_no_configurada_sin_filtrarla(world, monkeypatch, caplog, secret):
    monkeypatch.setenv("SESSION_SECRET", secret)
    r = world.client.get("/auth/challenge", params={"address": C1})
    assert r.status_code == 503 and r.json()["error"] == "AUTH_NOT_CONFIGURED"
    r = world.client.post("/auth/token", json={"transaction": "ficticia"})
    assert r.status_code == 503
    assert "al menos 32 caracteres" in caplog.text
    if secret:
        assert secret not in caplog.text and secret not in r.text


def test_session_32_caracteres_es_valida(world, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    assert world.client.get("/auth/challenge", params={"address": C1}).status_code == 200


def test_docker_no_confia_en_todas_las_ips_ni_publica_server():
    text = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "forwarded-allow-ips" not in text
    assert "--no-server-header" in text
