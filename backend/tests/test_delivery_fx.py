"""Vídeo, consentimiento por entrega y referencia de pesos sin red real."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main, fx
from backend.hashing import verdict_hash
from backend.state import StateStore
from backend.video import normalize_video
from backend.tests.test_evaluate_pagos import api, FakeChain, NOW, FREELANCER, ok_release  # noqa: F401

VIDEO = "https://drive.google.com/file/d/abcdefghijk1234567890/view?usp=sharing"
CANONICAL = "https://drive.google.com/file/d/abcdefghijk1234567890/preview"


@pytest.mark.parametrize("url", [VIDEO, CANONICAL, "https://drive.google.com/open?id=abcdefghijk1234567890"])
def test_video_canonico(url):
    assert normalize_video(url) == CANONICAL


@pytest.mark.parametrize("url", ["http://drive.google.com/file/d/abcdefghijk1234/view", "https://drive.google.com.evil.test/file/d/abcdefghijk1234/view", "https://evil.test/?drive.google.com", "javascript:alert(1)", "https://drive.google.com/drive/folders/abcdefghijk1234", "https://user@drive.google.com/file/d/abcdefghijk1234/view"])
def test_video_invalido(url):
    with pytest.raises(ValueError):
        normalize_video(url)


def test_consentimiento_tokens_persistencia_y_entrega_futura(api):
    evaluate, _, task_id = api(FakeChain(NOW + 600, ok_release))
    r = evaluate("import os\nos.environ\n").json()
    client = TestClient(main.app)
    task = main.store().tasks[task_id]
    endpoint = f"/tasks/{task_id}"
    ch = {"X-Client-Token": task["client_token"]}
    fh = {"X-Freelancer-Token": task["freelancer_token"]}
    assert client.get(endpoint + "/delivery", headers=ch).status_code == 409
    assert client.post(endpoint + "/consent", headers=ch).status_code == 403
    assert client.post(endpoint + "/consent", headers=fh, json={"code_hash": r["code_hash"]}).status_code == 200
    assert client.post(endpoint + "/consent", headers=fh).status_code == 200
    assert client.get(endpoint + "/delivery").status_code == 403
    assert client.get(endpoint + "/delivery", headers=ch).json()["code_hash"] == r["code_hash"]
    restored = StateStore(main.store().path)
    assert restored.tasks[task_id]["consented_code_hash"] == r["code_hash"]
    evaluate("import socket\nsocket.socket()\n")
    # La autorización anterior solo revela la entrega anterior, nunca el código nuevo.
    assert client.get(endpoint + "/delivery", headers=ch).json()["code_hash"] == r["code_hash"]
    assert task["latest_code_hash"] != task["consented_code_hash"]


def test_video_en_hash_cache_y_veredicto_sin_codigo(api):
    _, _, task_id = api(FakeChain(NOW + 600, ok_release))
    client = TestClient(main.app)
    task = main.store().tasks[task_id]
    body = {"task_id": task_id, "freelancer_address": FREELANCER, "code": "import os\nos.environ\n", "video_url": VIDEO}
    headers = {"X-Freelancer-Token": task["freelancer_token"]}
    r = client.post("/evaluate", headers=headers, json=body).json()
    assert r["verdict_hash"] == verdict_hash(task_id=task_id, code_hash=r["code_hash"], approved=r["approved"], reason=r["reason"], stage=r["stage"], comparison=r["comparison"], security_flags=r["security_flags"], video_url=CANONICAL)
    body["video_url"] = "https://drive.google.com/file/d/anotherfile123456/preview"
    cached = client.post("/evaluate", headers=headers, json=body).json()
    assert cached["stage"] == "cache" and cached["verdict_hash"] == r["verdict_hash"]
    v = client.get(f"/tasks/{task_id}/verdicts", headers={"X-Client-Token": task["client_token"]}).json()["verdicts"][0]
    assert v["video_url"] == CANONICAL
    assert not {"code", "trace", "logic", "analysis"}.intersection(v)


def test_aprobado_sin_video_cobra_y_no_admite_consentimiento(api):
    evaluate, _, task_id = api(FakeChain(NOW + 600, ok_release))
    r = evaluate().json()
    assert r["approved"] and r["transaction_hash"]
    task = main.store().tasks[task_id]
    client = TestClient(main.app)
    assert client.post(f"/tasks/{task_id}/consent", headers={"X-Freelancer-Token": task["freelancer_token"]}).status_code == 409
    assert client.get(f"/tasks/{task_id}/delivery", headers={"X-Client-Token": task["client_token"]}).json()["code_hash"] == r["code_hash"]


def test_fx_exito_cache_y_fecha(monkeypatch):
    response = httpx.Response(200, request=httpx.Request("GET", fx.URL), json={"rate": 19.1234, "date": "2026-09-23", "base": "USD", "quote": "MXN"})
    get = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    reference = fx.FxReference()
    first = asyncio.run(reference.get())
    assert first == asyncio.run(reference.get())
    assert first["rate"] == "19.1234" and first["as_of"] == "2026-09-23" and not first["fallback"]
    assert get.call_count == 1


def test_fx_caida_reintentos_y_respaldo(monkeypatch):
    get = AsyncMock(side_effect=httpx.ReadTimeout("sin red"))
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(fx.asyncio, "sleep", AsyncMock())
    result = asyncio.run(fx.FxReference().get())
    assert get.call_count == 3
    assert result == fx.FALLBACK
    assert result["rate"] == "17.50" and result["fallback"] is True


@pytest.mark.parametrize("rate", ["NaN", "-1", "Infinity", "0"])
def test_fx_invalido_no_reintenta(monkeypatch, rate):
    get = AsyncMock(return_value=httpx.Response(200, request=httpx.Request("GET", fx.URL), json={"rate": rate, "date": "2026-09-23", "base": "USD", "quote": "MXN"}))
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    assert asyncio.run(fx.FxReference().get())["fallback"]
    assert get.call_count == 1


def test_fx_fecha_utc_no_se_toma_como_futura(monkeypatch):
    # Frankfurter fecha en UTC: de 18:00 a 24:00 en México ya es el día siguiente, y no es futura.
    from datetime import datetime, timezone
    today_utc = datetime.now(timezone.utc).date().isoformat()
    response = httpx.Response(200, request=httpx.Request("GET", fx.URL), json={"rate": 17.5427, "date": today_utc, "base": "USD", "quote": "MXN"})
    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=response))
    result = asyncio.run(fx.FxReference().get())
    assert result["fallback"] is False and result["as_of"] == today_utc and result["rate"] == "17.5427"
