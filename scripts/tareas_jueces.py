"""Tareas para los jueces: N tareas depositadas por cyc-client y sus enlaces de invitación.

Uso (contra la versión pública; nunca antes de que pase la prueba de punta a punta):
  CYC_APP_URL=https://<frontend>.vercel.app CYC_API_URL=https://<backend>.up.railway.app \
    backend/.venv/Scripts/python scripts/tareas_jueces.py --n 5

  --comprobar   solo revisa el backend, el saldo de cyc-client y el contrato; no crea nada.
  --usdc 1      monto por tarea (USDC).      --dias 7   plazo on-chain (máximo del backend: 7 días).

Cada tarea usa la plantilla de la demo, la crea el backend con cyc-client como cliente y se deposita
con la Stellar CLI (la identidad cyc-client firma; el cliente on-chain coincide, así que /evaluate
no responde TASK_MISMATCH). Luego se confirma on-chain que quedó Funded.

Escribe los enlaces en docs/probar-en-linea.md (privado, ignorado por git). Los client_token quedan SOLO en
scripts/.logs/tareas-jueces.json (ignorado por git). Cada enlace lo toma la primera wallet que acepta.
Una tarea que nadie use devuelve su USDC a cyc-client con timeout_refund después del plazo.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.plantilla import DEMO_RAW_REQUEST, DEMO_SPEC  # noqa: E402

USDC_ISSUER = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
HORIZON = "https://horizon-testnet.stellar.org"
OUT = ROOT / "docs" / "probar-en-linea.md"
LOG = ROOT / "scripts" / ".logs" / "tareas-jueces.json"


def cli_address(identity: str) -> str:
    return subprocess.run(["stellar", "keys", "public-key", identity], capture_output=True, text=True,
                          check=True).stdout.strip()


def usdc_balance(address: str) -> Decimal:
    account = httpx.get(f"{HORIZON}/accounts/{address}", timeout=20).json()
    for b in account.get("balances", []):
        if b.get("asset_code") == "USDC" and b.get("asset_issuer") == USDC_ISSUER:
            return Decimal(b["balance"])
    return Decimal(0)


def deposit(contract_id: str, identity: str, task_id: str, units: int, deadline_secs: int, rules_hash: str) -> str:
    """El mismo deposit que scripts/deposit.sh, sin bash (en Windows, el bash de Python puede ser el de WSL)."""
    out = subprocess.run(["stellar", "contract", "invoke", "--id", contract_id, "--source", identity,
                          "--network", "testnet", "--", "deposit", "--client", identity,
                          "--task_id", json.dumps(task_id), "--amount", str(units),
                          "--deadline_secs", str(deadline_secs), "--rules_hash", rules_hash],
                         capture_output=True, text=True, encoding="utf-8")
    tx = re.findall(r"Signing transaction: ([0-9a-f]{64})", out.stdout + out.stderr)
    if out.returncode != 0 or not tx:
        raise RuntimeError(f"El depósito de {task_id} falló: {(out.stdout + out.stderr).strip()[:400]}")
    return tx[-1]


def wait_funded(api: str, task_id: str) -> dict:
    for _ in range(30):
        view = httpx.get(f"{api}/tasks/{task_id}", timeout=30).json()
        if (view.get("onchain") or {}).get("status") == "Funded":
            return view
        time.sleep(2)
    raise RuntimeError(f"La tarea {task_id} no aparece como Funded en el contrato")


def render_markdown(app: str, tasks: list[dict], usdc: str, days: int, generated_at: str) -> str:
    """docs/probar-en-linea.md: instrucciones para el juez y un enlace por tarea."""
    rows = "\n".join(
        f"| {i} | [`{t['task_id']}`]({t['invite']}) | {t['expires_at']} |" for i, t in enumerate(tasks, start=1))
    return f"""# Probar Cumple&Cobra en línea

Versión pública: **{app}** (testnet de Stellar; nada usa dinero real).

Cada enlace de abajo es una tarea real, ya depositada en el contrato por el cliente de la demo con **{usdc} USDC** de testnet
y un plazo de **{days} días**. El primer juez que la acepta queda amarrado a ella: si un enlace ya está tomado, usa el siguiente.

## Qué hacer (unos 5 minutos)

1. **Abre un enlace** de la tabla.
2. **Inicia sesión con Pollar** (botón arriba a la derecha) con tu correo: recibes un código y se crea tu wallet de Stellar.
   No necesitas XLM ni instalar nada.
3. **Activa USDC** cuando la página lo pida. Pollar patrocina la reserva, así que funciona con 0 XLM.
4. Revisa los criterios acordados y pulsa **«Acepto los criterios»**.
5. Elige **«Caso C: inyección en el docstring»** y pulsa **Enviar**: el Motor de Análisis Estático de Código basado en LLM lo
   **rechaza** por el intento de manipular al evaluador (verás el aviso de seguridad y el veredicto criterio por criterio).
6. Elige **«Caso A: implementación correcta»** y pulsa **Enviar**: se **aprueba** y el contrato te **paga** en segundos.
   Abre **«Ver transacción»** para ver el pago en el explorador de Stellar; el evento `release` lleva el `code_hash` y el
   `verdict_hash` del veredicto.
7. Opcional: en **Programadores** verás tu historial verificable; con **«Verificar identidad»** puedes firmar un reto SEP-10
   con tu wallet y publicar tu perfil.

Límites de la demo: máximo 3 envíos evaluados por tarea. Hay límites por conexión en ventanas de 60 segundos:
si aparece «Demasiadas solicitudes», espera el tiempo indicado y vuelve a intentar. Los rechazos por límite no consumen
esos 3 envíos. Además, hay cuotas diarias independientes para preparar pedidos (borrador y revisión) y evaluar código;
solo cuentan las llamadas reales a la IA, incluidos los reintentos. Si se agota la cuota diaria de tu operación, vuelve
al día siguiente (UTC). Las peticiones inválidas y las respuestas de caché no gastan cuota diaria.

## Tareas

| # | Tarea (enlace de invitación) | El plazo on-chain vence |
| --- | --- | --- |
{rows}

Generado el {generated_at} con `scripts/tareas_jueces.py`. Si una tarea no se usa, su depósito vuelve al cliente de la demo
con `timeout_refund` cuando vence el plazo.
"""


def positive_usdc(value: str) -> str:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("--usdc debe ser un número mayor que 0") from None
    if not amount.is_finite() or amount <= 0 or amount * 10_000_000 < 1:
        raise argparse.ArgumentTypeError("--usdc debe ser mayor que 0 y representar al menos una unidad del token")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, required=True, help="número de tareas")
    parser.add_argument("--usdc", default="1", type=positive_usdc)
    parser.add_argument("--dias", type=int, default=7)
    parser.add_argument("--identidad", default="cyc-client")
    parser.add_argument("--comprobar", action="store_true", help="solo revisa requisitos; no crea nada")
    parser.add_argument("--permitir-local", action="store_true", help="aceptar URLs de localhost (pruebas)")
    args = parser.parse_args()

    app = os.environ.get("CYC_APP_URL", "").rstrip("/")
    api = os.environ.get("CYC_API_URL", "").rstrip("/")
    if not app or not api:
        print("Faltan CYC_APP_URL y CYC_API_URL (las URLs públicas de Vercel y Railway).", file=sys.stderr)
        return 2
    if not args.permitir_local and any(urlsplit(u).scheme != "https" or "localhost" in u for u in (app, api)):
        print("Los enlaces para jueces deben ser públicos (https, sin localhost). Usa --permitir-local solo para pruebas.",
              file=sys.stderr)
        return 2
    if not 1 <= args.n <= 50 or not 1 <= args.dias <= 7:
        print("--n entre 1 y 50; --dias entre 1 y 7 (máximo del backend).", file=sys.stderr)
        return 2
    units = int(Decimal(args.usdc) * 10_000_000)
    contract_id = dotenv_values(ROOT / "backend" / ".env").get("CONTRACT_ID") or os.environ.get("CONTRACT_ID")

    # --- Requisitos -------------------------------------------------------------------------------
    health = httpx.get(f"{api}/health", timeout=30).json()
    client = cli_address(args.identidad)
    balance = usdc_balance(client)
    need = Decimal(units) / 10_000_000 * args.n
    print(f"Backend: {health} | cliente {args.identidad} {client} | USDC {balance} (necesita {need}) | contrato {contract_id}")
    if not health.get("ok") or not contract_id:
        print("El backend no responde /health o falta CONTRACT_ID.", file=sys.stderr)
        return 1
    if balance < need:
        print(f"Saldo insuficiente: faltan {need - balance} USDC en {client} (faucet de Circle, testnet).", file=sys.stderr)
        return 1
    if args.comprobar:
        print("Requisitos correctos; no se creó ninguna tarea (--comprobar).")
        return 0

    # --- Crear y depositar ------------------------------------------------------------------------------
    minutes = args.dias * 24 * 60
    created, log = [], {"app": app, "api": api, "client": client, "tasks": []}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for i in range(1, args.n + 1):
        r = httpx.post(f"{api}/tasks", timeout=30, json={
            "client_address": client, "raw_request": DEMO_RAW_REQUEST, **DEMO_SPEC,
            "amount": units, "deadline_minutes": minutes,
        })
        r.raise_for_status()
        task = r.json()
        tx = deposit(contract_id, args.identidad, task["task_id"], units, minutes * 60, task["rules_hash"])
        view = wait_funded(api, task["task_id"])
        expires = datetime.fromtimestamp(view["onchain"]["deadline"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        invite = f"{app}/tarea/{quote(task['task_id'])}?invitacion={quote(task['invite_token'])}"
        created.append({"task_id": task["task_id"], "invite": invite, "expires_at": expires})
        log["tasks"].append({**task, "deposit": tx, "expires_at": expires})
        LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")  # tokens solo aquí (ignorado por git)
        print(f"{i}/{args.n} tarea {task['task_id']} depositada: {tx}")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT.write_text(render_markdown(app, created, args.usdc, args.dias, generated), encoding="utf-8")
    print(f"Enlaces en {OUT.relative_to(ROOT)}; tokens del cliente en {LOG.relative_to(ROOT)}.")
    last = datetime.now(timezone.utc) + timedelta(days=args.dias)
    print(f"Después de {last:%Y-%m-%d %H:%M} UTC, las no usadas se reembolsan con timeout_refund (ver docs/demo.md).")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
