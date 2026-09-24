"""Mide la latencia del motor (capa 3) con los casos A, B y C, y verifica D.

Uso (desde la raíz):  backend/.venv/Scripts/python scripts/medir_latencia.py ETIQUETA [N]

Cada llamada usa exactamente la configuración del backend (gemini.build_config) y un
solo intento, sin reintentos, para medir la latencia real de Gemini. Guarda el detalle en
scripts/.logs/latencia-ETIQUETA.json e imprime la tabla con mediana y máximo.
"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import gemini  # noqa: E402
from backend.config import load_settings  # noqa: E402
from backend.deterministic import analyze  # noqa: E402
from backend.plantilla import DEMO_SPEC  # noqa: E402

CASOS = {"A": "a_feliz.py", "B": "b_calidad.py", "C": "c_inyeccion.py"}
ESPERADO = {"A": True, "B": False, "C": False}
ROOT = Path(__file__).resolve().parents[1]


async def una_llamada(client, model, code):
    config = gemini.build_config()
    prompt = gemini.build_prompt(DEMO_SPEC, code)
    t0 = time.monotonic()
    resp = await client.aio.models.generate_content(model=model, contents=prompt, config=config)
    secs = time.monotonic() - t0
    v = gemini._parse(resp.text, len(DEMO_SPEC["criteria"]))
    um = resp.usage_metadata
    approved = None
    if v is not None:
        approved = v.approved and not v.security_flags and all(
            c.lstrip().startswith("✓") for c in v.comparison)
    return {
        "segundos": round(secs, 2),
        "approved_final": approved,
        "security_flags": len(v.security_flags) if v else None,
        "trace": len(v.trace) if v else None,
        "logic": len(v.logic) if v else None,
        "tokens_razonamiento": um.thoughts_token_count if um else None,
        "tokens_salida": um.candidates_token_count if um else None,
        "reason": v.reason if v else None,
    }


async def main(label: str, n: int):
    sys.stdout.reconfigure(encoding="utf-8")
    s = load_settings()
    client = gemini.make_client(s)
    d = analyze((ROOT / "backend/casos/d_secretos.py").read_text(encoding="utf-8"), [])
    print(f"Caso D: ok={d.ok} security={d.security} (debe ser rechazo determinista)")
    resultados = {}
    for caso, archivo in CASOS.items():
        det = analyze((ROOT / "backend/casos" / archivo).read_text(encoding="utf-8"), [])
        assert det.ok
        corridas = []
        for i in range(n):
            r = await una_llamada(client, s.gemini_model, det.clean_code)
            corridas.append(r)
            print(f"  {caso} #{i + 1}: {r['segundos']:5.1f} s  approved={r['approved_final']}  "
                  f"flags={r['security_flags']}  trace={r['trace']} logic={r['logic']}  "
                  f"razonamiento={r['tokens_razonamiento']} salida={r['tokens_salida']}")
        resultados[caso] = corridas

    print(f"\n| Caso | Mediana (s) | Máximo (s) | Tokens de razonamiento (mediana) | Tokens de salida (mediana) | Veredictos correctos |")
    print("| --- | --- | --- | --- | --- | --- |")
    for caso, corridas in resultados.items():
        t = [c["segundos"] for c in corridas]
        th = [c["tokens_razonamiento"] or 0 for c in corridas]
        out = [c["tokens_salida"] or 0 for c in corridas]
        ok = sum(1 for c in corridas if c["approved_final"] == ESPERADO[caso])
        print(f"| {caso} | {statistics.median(t):.1f} | {max(t):.1f} | {statistics.median(th):.0f} | "
              f"{statistics.median(out):.0f} | {ok}/{len(corridas)} |")
    out_file = ROOT / "scripts/.logs" / f"latencia-{label}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5))
