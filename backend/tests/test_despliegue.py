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


# --- Railway: AI Studio sin Vertex, estado en el volumen, un solo proceso ------------------------------
def test_gemini_con_api_key_de_ai_studio_sin_credenciales_de_vertex(monkeypatch, tmp_path):
    from stellar_sdk import Keypair

    from backend import gemini
    from backend.config import load_settings

    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("ARBITER_SECRET_KEY", Keypair.random().secret)
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "data" / "state.json"))  # ruta absoluta del volumen
    settings = load_settings()
    assert settings.use_vertex is False and settings.gemini_api_key == "clave-de-prueba"
    assert settings.state_file == tmp_path / "data" / "state.json"
    assert gemini.make_client(settings).vertexai is False


def test_railway_un_solo_proceso_y_health_check():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    cfg = json.loads((root / "railway.json").read_text(encoding="utf-8"))
    assert cfg["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "backend/Dockerfile"}
    deploy = cfg["deploy"]
    assert deploy["numReplicas"] == 1 and deploy["overlapSeconds"] == 0
    assert deploy["requiredMountPath"] == "/data" and deploy["healthcheckPath"] == "/health"
    dockerfile = (root / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "--workers 1" in dockerfile and "STATE_FILE=/data/state.json" in dockerfile
    ignored = (root / ".dockerignore").read_text(encoding="utf-8")
    assert "backend/.env" in ignored and "backend/state.json" in ignored
