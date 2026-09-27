"""El diagnóstico temporal no expone direcciones ni se habilita por defecto."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.mark.parametrize("value", [None, "false", "1", "TRUE", ""])
def test_diagnostico_desactivado_responde_404(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DIAG_IP", raising=False)
    else:
        monkeypatch.setenv("DIAG_IP", value)
    assert TestClient(main.app).get("/_diag/ip").status_code == 404


def test_diagnostico_solo_nombres_y_hashes(monkeypatch):
    monkeypatch.setenv("DIAG_IP", "true")
    addresses = ["192.0.2.1", "198.51.100.2", "203.0.113.3"]
    response = TestClient(main.app).get("/_diag/ip", headers={
        "X-Forwarded-For": ", ".join(addresses[:2]),
        "X-Real-IP": addresses[2],
        "X-Envoy-External-Address": addresses[2],
        "CF-Connecting-IP": addresses[2],
        "Authorization": "valor-no-publicable",
    })
    digest = lambda value: hashlib.sha256(value.encode()).hexdigest()[:8]
    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert body["xff_count"] == 2
    assert body["xff_hashes"] == list(map(digest, addresses[:2]))
    assert body["client_host_hash"] == digest("testclient")
    assert body["limiter_key_hash"] == digest(addresses[1])
    assert body["header_names"] == ["cf-connecting-ip", "x-envoy-external-address", "x-forwarded-for", "x-real-ip"]
    assert body["header_hashes"]["x-real-ip"] == [digest(addresses[2])]
    assert all(value not in response.text for value in addresses + ["testclient", "valor-no-publicable", "authorization"])


def test_diagnostico_sin_forwarding(monkeypatch):
    monkeypatch.setenv("DIAG_IP", "true")
    body = TestClient(main.app).get("/_diag/ip").json()
    assert body["header_names"] == []
    assert body["xff_count"] == 0 and body["xff_hashes"] == []
    assert body["header_hashes"] == {}
    assert body["limiter_key_hash"] == body["client_host_hash"]
