"""Respaldo de la demo si Pollar no firma el depósito: tarea con la plantilla y depósito por CLI.

Uso: backend/.venv/Scripts/python scripts/tarea_respaldo.py [--usdc 1] [--minutos 10] [--identidad cyc-client]

El depósito de scripts/deposit.sh se hace con una identidad de la Stellar CLI, y /evaluate exige que el cliente
on-chain sea el mismo que creó la tarea (si no, TASK_MISMATCH). Por eso una tarea creada con la
wallet de Pollar no se puede depositar con deposit.sh: este script crea la tarea con la dirección
de la identidad de la CLI y la deposita con ella. Imprime el enlace de invitación para el
programador (que sigue en el navegador con Pollar). Los tokens quedan solo en
scripts/.logs/tarea-respaldo-<task_id>.json (ignorado por git).
"""
import argparse
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.plantilla import DEMO_RAW_REQUEST, DEMO_SPEC  # noqa: E402

API = "http://localhost:8000"
APP = "http://localhost:3000"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usdc", default="1", help="monto en USDC, hasta 7 decimales")
    parser.add_argument("--minutos", type=int, default=10)
    parser.add_argument("--identidad", default="cyc-client")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+(\.\d{1,7})?", args.usdc):
        print("Monto inválido: usa USDC con hasta 7 decimales (ej. 1 o 0.5)", file=sys.stderr)
        return 2
    units = int(Decimal(args.usdc) * 10_000_000)

    client = subprocess.run(["stellar", "keys", "public-key", args.identidad],
                            capture_output=True, text=True, check=True).stdout.strip()
    created = httpx.post(f"{API}/tasks", timeout=30, json={
        "client_address": client, "raw_request": DEMO_RAW_REQUEST, **DEMO_SPEC,
        "amount": units, "deadline_minutes": args.minutos,
    })
    created.raise_for_status()
    task = created.json()
    log = ROOT / "scripts" / ".logs" / f"tarea-respaldo-{task['task_id']}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({**task, "client_address": client, "amount": units}, indent=1), encoding="utf-8")
    print(f"Tarea {task['task_id']} creada con {args.identidad} ({client}) como cliente")

    # Mismo deposit que scripts/deposit.sh, invocado sin bash: en Windows, "bash" desde Python puede
    # ser el de WSL, sin la Stellar CLI en su PATH.
    contract_id = dotenv_values(ROOT / "backend" / ".env").get("CONTRACT_ID")
    print(f"Depositando {units} unidades (plazo {args.minutos * 60} s) desde {args.identidad}")
    deposit = subprocess.run(["stellar", "contract", "invoke", "--id", contract_id, "--source", args.identidad,
                              "--network", "testnet", "--", "deposit", "--client", args.identidad,
                              "--task_id", json.dumps(task["task_id"]), "--amount", str(units),
                              "--deadline_secs", str(args.minutos * 60), "--rules_hash", task["rules_hash"]],
                             capture_output=True, text=True, encoding="utf-8")
    out = deposit.stdout + deposit.stderr
    tx = re.findall(r"Signing transaction: ([0-9a-f]{64})", out)
    if deposit.returncode != 0 or not tx:
        print(out.strip(), file=sys.stderr)
        return 1
    print(f"Transacción: {tx[-1]}\nhttps://stellar.expert/explorer/testnet/tx/{tx[-1]}")
    print(f"\nEnlace para el programador (no lo publiques):\n{APP}/tarea/{task['task_id']}?invitacion={task['invite_token']}")
    print(f"\nVeredictos del cliente (el client_token está en {log.relative_to(ROOT)}):")
    print(f"curl -s -H \"X-Client-Token: $(backend/.venv/Scripts/python -c \"import json;print(json.load(open('{log.relative_to(ROOT).as_posix()}'))['client_token'])\")\" {API}/tasks/{task['task_id']}/verdicts")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
