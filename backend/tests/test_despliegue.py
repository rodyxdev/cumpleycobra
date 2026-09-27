"""Despliegue: nada debe asumir localhost; dominios y orígenes salen del entorno."""

import pytest

from backend import identidad, main


def test_varios_origenes_cors_sin_barra_final():
    assert main.frontend_origins("https://cumpleycobra.vercel.app/, https://prev.vercel.app") == [
        "https://cumpleycobra.vercel.app", "https://prev.vercel.app"]
    assert main.frontend_origins("http://localhost:3000") == ["http://localhost:3000"]


@pytest.mark.parametrize("env, home, web", [
    ({}, "localhost:3000", "localhost:8000"),
    ({"FRONTEND_ORIGIN": "https://cumpleycobra.vercel.app,https://otro.app"}, "cumpleycobra.vercel.app", "localhost:8000"),
    ({"FRONTEND_ORIGIN": "https://cumpleycobra.vercel.app", "RAILWAY_PUBLIC_DOMAIN": "api.up.railway.app"},
     "cumpleycobra.vercel.app", "api.up.railway.app"),
    ({"SEP10_HOME_DOMAIN": "a.example", "SEP10_WEB_AUTH_DOMAIN": "b.example", "RAILWAY_PUBLIC_DOMAIN": "x"},
     "a.example", "b.example"),
])
def test_dominios_sep10_desde_el_entorno(monkeypatch, env, home, web):
    for name in ("SEP10_HOME_DOMAIN", "SEP10_WEB_AUTH_DOMAIN", "RAILWAY_PUBLIC_DOMAIN", "FRONTEND_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert identidad.home_domain() == home and identidad.web_auth_domain() == web
