"""scripts/tareas_jueces.py: el documento para jueces y los candados de seguridad (sin crear tareas)."""

import argparse
import pytest
import subprocess
import sys
from pathlib import Path

from scripts.tareas_jueces import positive_usdc, render_markdown

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "tareas_jueces.py"


def test_documento_para_jueces_con_enlaces_e_instrucciones():
    tasks = [{"task_id": "AbC123xYz", "invite": "https://app.vercel.app/tarea/AbC123xYz?invitacion=tok", "expires_at": "2026-10-03 12:00 UTC"}]
    md = render_markdown("https://app.vercel.app", tasks, "1", 7, "2026-09-26 12:00 UTC")
    assert "[`AbC123xYz`](https://app.vercel.app/tarea/AbC123xYz?invitacion=tok)" in md
    for step in ("Inicia sesión con Pollar", "Activa USDC", "Acepto los criterios", "Caso C", "Caso A", "Ver transacción"):
        assert step in md
    assert "simulación" not in md.lower()


def run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                          env={"PATH": "", "PYTHONUTF8": "1", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), **(env or {})})


def test_exige_urls_publicas_antes_de_tocar_la_red():
    r = run("--n", "2")
    assert r.returncode == 2 and "CYC_APP_URL" in r.stderr
    r = run("--n", "2", env={"CYC_APP_URL": "http://localhost:3000", "CYC_API_URL": "http://localhost:8000"})
    assert r.returncode == 2 and "públicos" in r.stderr
    r = run("--n", "0", env={"CYC_APP_URL": "https://a.vercel.app", "CYC_API_URL": "https://b.up.railway.app"})
    assert r.returncode == 2 and "--n" in r.stderr


@pytest.mark.parametrize("value", ["0", "-1", "-0.001", "NaN", "Infinity", "texto", "0.000000001"])
def test_usdc_invalido_no_toca_red(value):
    with pytest.raises(argparse.ArgumentTypeError, match="mayor que 0"):
        positive_usdc(value)


def test_cli_rechaza_monto_antes_de_leer_configuracion():
    r = run("--n", "1", "--usdc", "0")
    assert r.returncode == 2 and "mayor que 0" in r.stderr
    assert "Faltan CYC_APP_URL" not in r.stderr


@pytest.mark.parametrize("value", ["1", "0.25", "0.0000001"])
def test_usdc_positivo(value):
    assert positive_usdc(value) == value


def test_invitaciones_privadas_y_ejemplo_sin_enlaces():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "docs/probar-en-linea.md" in ignored
    example = (ROOT / "docs/probar-en-linea.ejemplo.md").read_text(encoding="utf-8")
    assert "http" not in example and "invitacion=" not in example
    assert "cuotas diarias independientes" in example
    generated = render_markdown("dominio de prueba", [], "1", 7, "fecha de prueba")
    assert "cuotas diarias independientes" in generated
    assert "respuestas de caché no gastan cuota diaria" in generated
