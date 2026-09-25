"""Prueba real de «Revisar criterios»: criterios de la demo más «Que sea rápido».

Uso: backend/.venv/Scripts/python scripts/probar_revision.py [--runs 3]
Llama a Vertex con pausas (cuota) y comprueba que ninguna sugerencia nombre construcciones
concretas de código. Evidencia en docs/fases/fase-4a-revision.json. Código de salida 1 si falla.
"""
import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import drafting, gemini  # noqa: E402
from backend.config import load_settings  # noqa: E402
from backend.plantilla import DEMO_SPEC  # noqa: E402

PAUSE_SECS = 10
CONSTRUCTS = re.compile(
    r"comprensi|bucle|\bfor\b|\bwhile\b|auxiliar|helper|lambda|\bmap\b|recursi",
    re.IGNORECASE,
)
OUT = ROOT / "docs/fases/fase-4a-revision.json"


async def main(runs: int) -> int:
    settings = load_settings()
    client = gemini.make_client(settings)
    criteria = [*DEMO_SPEC["criteria"], "Que sea rápido"]
    results, failures = [], 0
    for run in range(1, runs + 1):
        if run > 1:
            await asyncio.sleep(PAUSE_SECS)
        started = time.monotonic()
        review = await drafting.review(client, settings.gemini_model, criteria)
        items = [item.model_dump() for item in review.criteria]
        vague = [i for i in items if i["vague"]]
        target = items[-1]
        named = sorted({m.group(0).lower() for i in vague for m in CONSTRUCTS.finditer(i["suggestion"])})
        ok = target["vague"] and not named
        failures += not ok
        results.append({"run": run, "seconds": round(time.monotonic() - started, 1),
                        "criteria": items, "constructs_named": named, "ok": ok})
        print(f"Corrida {run}: {'correcta' if ok else 'INCORRECTA'} "
              f"({results[-1]['seconds']} s, vagos: {[i['index'] for i in vague]})")
        print(f"  «Que sea rápido» → {target['suggestion']}")
        for i in vague[:-1] if target["vague"] else vague:
            print(f"  criterio {i['index']} → {i['suggestion']}")
        if named:
            print(f"  Construcciones nombradas: {named}")
    OUT.write_text(json.dumps({
        "model": settings.gemini_model,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_criteria": criteria,
        "runs": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Resultado: {runs - failures}/{runs} correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    sys.exit(asyncio.run(main(parser.parse_args().runs)))
