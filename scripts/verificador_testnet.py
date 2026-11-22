"""Recorrido real de la verificación por ejecución en testnet (fase 3), sin el navegador.

Crea una tarea con verification: "execution" usando la plantilla de la demo, espera la suite oculta
(la genera el modelo y la valida el verificador), deposita con la Stellar CLI (scripts/deposit.sh),
acepta como programador y entrega uno o varios casos de backend/casos/. Necesita la API con
VERIFIER_ENABLED y un trabajador corriendo (`python -m verifier.worker`).

Uso:
    backend/.venv/Scripts/python scripts/verificador_testnet.py --casos b_calidad.py a_feliz.py
    backend/.venv/Scripts/python scripts/verificador_testnet.py --web --casos formulario-get correcta

Con --web usa el acuerdo del Café Luna (scripts/corpus_verificador/web_cafe.py): los casos son ids
de sus entregas, que se suben como ZIP, y el sitio se revisa en un navegador real.

Los tokens se guardan en scripts/.logs/verificador-<task_id>.json (ignorado por git); nunca se imprimen.
"""
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("CYC_API_URL", "http://localhost:8000").rstrip("/")
sys.path.insert(0, str(ROOT))
from backend.plantilla import DEMO_RAW_REQUEST, DEMO_SPEC  # noqa: E402
from scripts.corpus_verificador import web_cafe  # noqa: E402

INTERFACE = {"language": "python", "symbols": [{
    "module": "descuentos", "name": "aplicar_descuento", "kind": "function",
    "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]"}]}


def address(identity: str) -> str:
    return subprocess.run(["stellar", "keys", "address", identity], capture_output=True, text=True, check=True).stdout.strip()


def wait(fn, what: str, timeout: float = 600, every: float = 2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(every)
    raise SystemExit(f"Se agotó la espera: {what}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--casos", nargs="+", default=["a_feliz.py"])
    parser.add_argument("--minutos", type=int, default=30)
    parser.add_argument("--unidades", type=int, default=10_000_000)
    parser.add_argument("--cliente", default="cyc-client")
    parser.add_argument("--programador", default="cyc-freelancer")
    parser.add_argument("--tarea", help="retomar una tarea ya creada (lee sus tokens de scripts/.logs)")
    parser.add_argument("--web", action="store_true", help="tarea de perfil web (Café Luna)")
    args = parser.parse_args()
    http = httpx.Client(base_url=API, timeout=60)
    client, freelancer = address(args.cliente), address(args.programador)

    t0 = time.monotonic()
    logs = ROOT / "scripts" / ".logs"
    if args.tarea:
        created = json.loads((logs / f"verificador-{args.tarea}.json").read_text(encoding="utf-8"))
    else:
        acuerdo = ({"raw_request": "", **web_cafe.ACUERDO} if args.web
                   else {"raw_request": DEMO_RAW_REQUEST, **DEMO_SPEC, "interface": INTERFACE})
        created = http.post("/tasks", json={"client_address": client, **acuerdo, "amount": args.unidades,
                                            "deadline_minutes": args.minutos, "verification": "execution"}
                            ).raise_for_status().json()
    tid = created["task_id"]
    logs.mkdir(exist_ok=True)
    (logs / f"verificador-{tid}.json").write_text(json.dumps(created, indent=1), encoding="utf-8")
    print(f"tarea {tid} · rules_hash {created['rules_hash']}")

    def suite_done():
        plan = http.get(f"/tasks/{tid}/suite").json()
        return plan if plan["status"] in ("lista", "rechazada") else None

    plan = wait(suite_done, "suite oculta")
    print(f"suite {plan['status']} en {time.monotonic() - t0:.1f} s · suite_hash {plan['suite_hash']}")
    for c in plan["criteria"]:
        print(f"  criterio {c['index']}: {c['tipo']} · {len(c['plan'])} tests")
    if plan["status"] != "lista":
        return 1

    onchain = http.get(f"/tasks/{tid}").json().get("onchain")
    if onchain:
        print(f"ya depositada: {onchain['status']}")
    else:
        # Mismo comando que scripts/deposit.sh, sin pasar por bash (en Windows, `bash` puede ser WSL).
        contract = os.environ.get("CONTRACT_ID") or dotenv_values(ROOT / "backend" / ".env").get("CONTRACT_ID")
        dep = subprocess.run(["stellar", "contract", "invoke", "--id", contract, "--source", args.cliente, "--network",
                              "testnet", "--", "deposit", "--client", args.cliente, "--task_id", f'"{tid}"',
                              "--amount", str(args.unidades), "--deadline_secs", str(args.minutos * 60),
                              "--rules_hash", created["rules_hash"]], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        tx = re.findall(r"Signing transaction: ([0-9a-f]{64})", dep.stdout + dep.stderr)
        if dep.returncode != 0 or not tx:
            print("el depósito falló:", (dep.stdout + dep.stderr)[-800:])
            return 1
        print(f"depósito {tx[-1]}")
    accepted = http.post(f"/tasks/{tid}/accept", json={"freelancer_address": freelancer,
                                                        "invite_token": created["invite_token"]}).raise_for_status().json()
    created["freelancer_token"] = accepted["freelancer_token"]
    (logs / f"verificador-{tid}.json").write_text(json.dumps(created, indent=1), encoding="utf-8")
    headers = {"X-Freelancer-Token": accepted["freelancer_token"]}

    entregas = {e["id"]: e for e in web_cafe.ENTREGAS}
    for caso in args.casos:
        if args.web:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for name, text in entregas[caso]["files"].items():
                    zf.writestr(name, text)
            source = {"kind": "zip", "zip_b64": base64.b64encode(buf.getvalue()).decode()}
        else:
            source = {"kind": "code", "code": (ROOT / "backend" / "casos" / caso).read_text(encoding="utf-8")}
        t1 = time.monotonic()
        r = http.post(f"/tasks/{tid}/verificaciones", headers=headers,
                      json={"freelancer_address": freelancer, "source": source})
        if r.status_code != 202:
            print(f"{caso}: {r.status_code} {r.text}")
            return 1
        vid = r.json()["verification_id"]

        def finished():
            s = http.get(f"/verificaciones/{vid}", headers=headers).json()
            return s if s["status"] in ("done", "failed") else None

        status = wait(finished, f"verificación de {caso}", every=1.5)
        stages = " → ".join(p["stage"] for p in status["progress"])
        res = status.get("result") or {}
        print(f"{caso}: {status['status']} en {time.monotonic() - t1:.1f} s ({stages})")
        print(f"  approved={res.get('approved')} stage={res.get('stage')} tx={res.get('transaction_hash')}")
        print(f"  verdict_hash={res.get('verdict_hash')} code_hash={res.get('code_hash')}")
        for line in res.get("comparison", []):
            print("   ", line[:150])
        shots = (res.get("verification") or {}).get("screenshots") or []
        if shots:
            first = http.get(shots[0]["url"]) if shots[0].get("url") else None
            print(f"  capturas: {', '.join(s['id'] + '@' + s['viewport'] for s in shots)} · "
                  f"{shots[0]['id']} por URL firmada: {first.status_code if first else 'sin URL'} "
                  f"{first.headers.get('content-type') if first else ''}")
        if res.get("transaction_hash"):
            print(f"  https://stellar.expert/explorer/testnet/tx/{res['transaction_hash']}")
            break
    onchain = http.get(f"/tasks/{tid}").json().get("onchain") or {}
    print(f"on-chain: {onchain.get('status')} · programador {onchain.get('freelancer')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
