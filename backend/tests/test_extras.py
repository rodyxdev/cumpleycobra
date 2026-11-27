"""Funciones experimentales de Ship It (backend/extras.py), detrás de EXTRAS_ENABLED."""

import xml.etree.ElementTree as ET

from backend import extras

from .test_reputacion import C1, C2, FakeEvents, P1, P2, rate, world  # noqa: F401 - fixture
from backend import main


def test_sin_bandera_la_insignia_no_existe(world, monkeypatch):
    monkeypatch.delenv("EXTRAS_ENABLED", raising=False)
    assert world.client.get(f"/programadores/{P1}/insignia.svg").status_code == 404


def test_insignia_con_pagos_confirmados_on_chain_y_calificacion(world, monkeypatch):
    monkeypatch.setenv("EXTRAS_ENABLED", "true")
    a, ta = world.task(P1, C1)
    world.task(P1, C2, engine=False)
    world.task(P1, C2, status="Funded")  # state dice release, la cadena no: no cuenta
    main.app.state.payment_events = FakeEvents()
    rate(world, a, ta, estrellas=5)

    r = world.client.get(f"/programadores/{P1}/insignia.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=300" in r.headers["cache-control"]
    svg = ET.fromstring(r.text)  # SVG bien formado
    texts = [t.text for t in svg.iter("{http://www.w3.org/2000/svg}text")]
    assert texts == ["Cumple&Cobra", "2 pagadas · ★ 5.0"]


def test_insignia_sin_pagos_y_direccion_invalida(world, monkeypatch):
    monkeypatch.setenv("EXTRAS_ENABLED", "1")
    r = world.client.get(f"/programadores/{P2}/insignia.svg")
    assert r.status_code == 200 and "0 pagadas" in r.text and "★" not in r.text
    assert world.client.get("/programadores/hola/insignia.svg").status_code == 400


def test_badge_svg_escapa_y_usa_singular():
    svg = extras.badge_svg({"engine_paid": 1, "manual_paid": 0, "rating_average": None})
    root = ET.fromstring(svg)
    assert "1 pagada" in svg and "pagadas" not in svg
    assert root.attrib["aria-label"].startswith("Cumple&Cobra: 1 pagada")


def test_comprobante_solo_con_bandera_y_tarea_pagada(world, monkeypatch):
    monkeypatch.delenv("EXTRAS_ENABLED", raising=False)
    tid, _ = world.task(P1, C1)
    assert world.client.get(f"/tasks/{tid}/comprobante").status_code == 404
    monkeypatch.setenv("EXTRAS_ENABLED", "true")
    funded, _ = world.task(P1, C1, status="Funded")
    r = world.client.get(f"/tasks/{funded}/comprobante")
    assert r.status_code == 409 and r.json()["error"] == "TASK_NOT_RELEASED"
    assert world.client.get("/tasks/no-existe/comprobante").status_code == 404


def test_comprobante_del_motor_con_hashes_y_sin_datos_privados(world, monkeypatch):
    monkeypatch.setenv("EXTRAS_ENABLED", "true")
    tid, _ = world.task(P1, C1)
    main.app.state.payment_events = FakeEvents(
        {tid: {"paid_by": "motor", "transaction_hash": "e1" * 32, "paid_at": "2026-11-26T15:04:26Z"}})
    body = world.client.get(f"/tasks/{tid}/comprobante").json()
    assert body["programador"] == P1 and body["paid_by"] == "motor"
    assert body["explorer_url"].endswith("e1" * 32)
    assert body["rules_hash_matches"] is True
    assert body["code_hash"] == "c9" * 32 and body["verdict_hash"] == "cd" * 32
    assert body["contract_url"].endswith("/contract/C")
    text = str(body)
    for private in ("client_token", "invite_token", C1, "trace", "logic"):
        assert private not in text


def test_comprobante_de_pago_manual_sin_hashes_del_motor(world, monkeypatch):
    monkeypatch.setenv("EXTRAS_ENABLED", "true")
    tid, _ = world.task(P2, C2, engine=False)
    main.app.state.payment_events = FakeEvents()
    body = world.client.get(f"/tasks/{tid}/comprobante").json()
    assert body["paid_by"] == "manual" and body["code_hash"] is None and body["verdict_hash"] is None
