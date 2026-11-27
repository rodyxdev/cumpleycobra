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
