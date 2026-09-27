"""scripts/tareas_jueces.py: el documento para jueces y los candados de seguridad (sin crear tareas)."""

import subprocess
import sys
from pathlib import Path

from scripts.tareas_jueces import render_markdown

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
