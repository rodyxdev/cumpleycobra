"""Diez repeticiones por caso A–D y estudio de 20 casos distintos, sin cadena.

backend/.venv/Scripts/python scripts/estabilizar_motor.py [--salida docs/fases/otro.json]
Expectativas fijadas en corpus_motor.json antes de medir. No ejecuta las entregas.
Máximo 8 llamadas/minuto, incluyendo reintentos. No usar junto a otra medición.
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import gemini  # noqa: E402
from backend.config import load_settings  # noqa: E402
from backend.deterministic import analyze  # noqa: E402
from backend.hashing import code_hash  # noqa: E402
from backend.plantilla import DEMO_SPEC  # noqa: E402
from scripts.probar_pedido import Pace, time_ok  # noqa: E402

OUT = ROOT / "docs/fases/fase-5-motor.json"


async def main(out: Path = OUT):
    settings = load_settings()
    client = gemini.make_client(settings)
    pace = Pace()
    corpus = json.loads((ROOT / "scripts/corpus_motor.json").read_text(encoding="utf-8"))
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "model": settings.gemini_model,
              "spec": DEMO_SPEC, "call_starts": pace.starts, "stability": [], "study": []}

    async def sample(case):
        code = (ROOT / case["file"]).read_text(encoding="utf-8") if "file" in case else case["code"]
        result = {"id": case["id"], "expected": case["approved"], "code_hash": code_hash(code)}
        started = time.monotonic()
        waits = 0

        async def before():
            nonlocal waits
            t = time.monotonic()
            await pace.wait()
            waits += time.monotonic() - t

        try:
            det = analyze(code, DEMO_SPEC["allowed_deps"])
            if not det.ok:
                result.update(approved=False, stage="deterministic", reason=det.reason, security_flags=det.problems if det.security else [])
            else:
                v, _ = await gemini.evaluate(client, settings.gemini_model, DEMO_SPEC, det.clean_code, time_ok, before_attempt=before)
                result.update(v.model_dump(), stage="llm")
                result["approved"] = bool(v.approved and not v.security_flags and all(c.lstrip().startswith("✓") for c in v.comparison))
            result["correct"] = (result["approved"] == case["approved"] and (not case.get("security") or bool(result["security_flags"])))
        except gemini.EngineUnavailable as exc:
            result.update(error=str(exc), correct=False)
        result["seconds"] = round(time.monotonic() - started - waits, 3)
        return result

    def save():
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for case in corpus[:4]:
            for repeat in range(1, 11):
                result = await sample(case)
                result["repeat"] = repeat
                report["stability"].append(result)
                save()
                print(f"Estabilidad {case['id']} {repeat}/10: {result['correct']} ({result['seconds']:.2f} s)", flush=True)
        for case in corpus:
            result = await sample(case)
            report["study"].append(result)
            save()
            print(f"Estudio {case['id']}: {result['correct']} ({result['seconds']:.2f} s)", flush=True)
    finally:
        await client.aio.aclose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = all(r["correct"] for r in report["stability"] + report["study"])
    for label in ("stability", "study"):
        values = report[label]
        latencies = [r["seconds"] for r in values if r.get("stage") == "llm"]
        report[label + "_summary"] = {"correct": sum(r["correct"] for r in values), "total": len(values),
                                       "llm_median_s": round(statistics.median(latencies), 3), "llm_max_s": max(latencies)}
    save()
    print(json.dumps({k: v for k, v in report.items() if k.endswith("summary")}, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--salida", type=Path, default=OUT, help="JSON de salida (por defecto, el de la fase 5)")
    sys.exit(asyncio.run(main(parser.parse_args().salida)))
