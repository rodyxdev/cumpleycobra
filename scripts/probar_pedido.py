"""Cinco borradores reales y casos A–D; no importa ni invoca el cliente de cadena.

Desde la raíz: backend/.venv/Scripts/python scripts/probar_pedido.py
Guarda evidencia JSON y Markdown en docs/fases/. Cada intento (también reintentos)
se inicia al menos 8 segundos después del anterior: máximo 8 llamadas/minuto.
"""

import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import drafting, gemini  # noqa: E402
from backend.config import load_settings  # noqa: E402
from backend.deterministic import analyze  # noqa: E402
from backend.hashing import code_hash, rules_hash  # noqa: E402
from backend.plantilla import DEMO_RAW_REQUEST  # noqa: E402

CASES = {"A": "a_feliz.py", "B": "b_calidad.py", "C": "c_inyeccion.py", "D": "d_secretos.py"}


class Pace:
    def __init__(self):
        self.last = float("-inf")
        self.starts = []

    async def wait(self):
        await asyncio.sleep(max(0, 8 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.starts.append(datetime.now(timezone.utc).isoformat())


async def time_ok():
    return True  # prueba sin depósito ni plazo on-chain


def save(report):
    base = ROOT / "docs/fases"
    (base / "fase-4a-pedido.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Prueba real del pedido asistido", "", f"Modelo: `{report['model']}`. Inicio UTC: {report['started_at']}.",
             "", "Máximo 8 llamadas/minuto; todos los intentos separados por al menos 8 s. Sin cadena.", "",
             "| Borrador | A | B | C | D |", "| --- | --- | --- | --- | --- |"]
    for row in report["drafts"]:
        cells = []
        for case in CASES:
            result = row["cases"].get(case)
            if not result:
                cells.append("Pendiente")
            elif result.get("error"):
                cells.append("ERROR")
            else:
                verdict = "Aprobado" if result["approved"] else "Rechazado"
                cells.append(f"{verdict} ({result['seconds']:.1f} s, {result['stage']})")
        lines.append(f"| {row['number']} | " + " | ".join(cells) + " |")
    for row in report["drafts"]:
        lines += ["", f"## Borrador {row['number']}", ""]
        if row.get("error"):
            lines.append(row["error"])
            continue
        spec = row["spec"]
        lines += [spec["description"], "", f"`rules_hash`: `{row['rules_hash']}`", ""]
        lines += [f"{i}. {criterion}" for i, criterion in enumerate(spec["criteria"], 1)]
        lines += ["", "Ejemplos:", ""]
        lines += [f"- Entrada: `{e['input']}` → salida: `{e['output']}`" for e in spec["examples"]]
    (base / "fase-4a-pedido.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main():
    settings = load_settings()
    client = gemini.make_client(settings)
    pace = Pace()
    codes = {case: (ROOT / "backend/casos" / name).read_text(encoding="utf-8") for case, name in CASES.items()}
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "model": settings.gemini_model,
              "raw_request": DEMO_RAW_REQUEST,
              "instruction_sha256": hashlib.sha256(drafting.DRAFT_INSTRUCTION.encode()).hexdigest(),
              "code_hashes": {case: code_hash(code) for case, code in codes.items()},
              "call_starts": pace.starts, "drafts": []}
    all_ok = True
    try:
        for number in range(1, 6):
            row = {"number": number, "cases": {}}
            report["drafts"].append(row)
            try:
                spec = (await drafting.draft(client, settings.gemini_model, DEMO_RAW_REQUEST,
                                             before_attempt=pace.wait)).model_dump()
                row.update(spec=spec, rules_hash=rules_hash(spec))
                print(f"Borrador {number}: {len(spec['criteria'])} criterios", flush=True)
                for case, code in codes.items():
                    started = time.monotonic()
                    try:
                        det = analyze(code, spec["allowed_deps"])
                        if not det.ok:
                            result = {"approved": False, "stage": "deterministic", "reason": det.reason,
                                      "security_flags": det.problems if det.security else [], "comparison": []}
                        else:
                            verdict, _ = await gemini.evaluate(client, settings.gemini_model, spec,
                                                               det.clean_code, time_ok, before_attempt=pace.wait)
                            result = {**verdict.model_dump(), "stage": "llm"}
                            # Misma regla final de /evaluate, sin pago ni estado persistido.
                            result["approved"] = bool(verdict.approved and not verdict.security_flags
                                                      and all(c.lstrip().startswith("✓") for c in verdict.comparison))
                        result["seconds"] = round(time.monotonic() - started, 2)
                        result["expected"] = case == "A"
                        result["correct"] = (result["approved"] == result["expected"]
                                             and (case != "C" or bool(result["security_flags"]))
                                             and (case != "D" or result["stage"] == "deterministic"))
                        all_ok = all_ok and result["correct"]
                    except gemini.EngineUnavailable as exc:
                        result = {"error": str(exc), "correct": False}
                        all_ok = False
                    row["cases"][case] = result
                    print(f"  {case}: approved={result.get('approved')} correcto={result['correct']} {result.get('stage', 'ERROR')}", flush=True)
                    save(report)
            except gemini.EngineUnavailable as exc:
                row["error"] = str(exc)
                all_ok = False
                print(f"Borrador {number}: {exc}", flush=True)
            save(report)
    finally:
        await client.aio.aclose()
    report["passed"] = all_ok
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save(report)
    print(f"Resultado: {'20/20 correctos' if all_ok else 'FALLO; consultar evidencia'}; intentos Gemini: {len(pace.starts)}", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
