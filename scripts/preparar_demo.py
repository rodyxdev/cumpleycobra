"""Prepara dos cuentas de testnet, Friendbot y trustlines de USDC.

Uso: backend/.venv/Scripts/python scripts/preparar_demo.py --fund-from cyc-client
Idempotente. Las llaves generadas quedan SOLO en scripts/.logs/demo-accounts.json
(ignorado por git); el informe público nunca las incluye. No opera en mainnet.
El fondeo opcional usa una identidad de Stellar CLI que ya tenga USDC de testnet.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import httpx
from stellar_sdk import Asset, Keypair, Network, Server, TransactionBuilder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import load_settings  # noqa: E402

HORIZON = "https://horizon-testnet.stellar.org"
ASSET = Asset("USDC", "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5")
ACCOUNTS = ROOT / "scripts/.logs/demo-accounts.json"


def request(method, url, **kwargs):
    for attempt in range(3):
        try:
            r = httpx.request(method, url, timeout=30, **kwargs)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < 2:
                time.sleep((1, 3)[attempt]); continue
            return r
        except httpx.TransportError:
            if attempt == 2: raise
            time.sleep((1, 3)[attempt])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fund-from", help="Identidad de Stellar CLI con USDC de testnet")
    args = parser.parse_args()
    if load_settings().network_passphrase != Network.TESTNET_NETWORK_PASSPHRASE:
        raise SystemExit("Esta preparación solo permite testnet")
    if not ACCOUNTS.exists():
        ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
        keys = {role: Keypair.random().secret for role in ("cliente", "programador")}
        with ACCOUNTS.open("x", encoding="utf-8") as f:
            json.dump(keys, f)
        os.chmod(ACCOUNTS, 0o600)
    else:
        keys = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    server = Server(HORIZON)
    report = {"network": "testnet", "accounts": {}}
    for role, secret in keys.items():
        kp = Keypair.from_secret(secret)
        result = {"address": kp.public_key, "transactions": []}
        r = request("GET", f"{HORIZON}/accounts/{kp.public_key}")
        if r.status_code == 404:
            funded = request("GET", "https://friendbot.stellar.org", params={"addr": kp.public_key})
            funded.raise_for_status()
            result["friendbot"] = funded.json().get("hash")
            r = request("GET", f"{HORIZON}/accounts/{kp.public_key}")
        r.raise_for_status()
        balances = r.json()["balances"]
        usdc = next((b for b in balances if b.get("asset_code") == ASSET.code and b.get("asset_issuer") == ASSET.issuer), None)
        if usdc is None:
            tx = (TransactionBuilder(server.load_account(kp.public_key), Network.TESTNET_NETWORK_PASSPHRASE, base_fee=100)
                  .append_change_trust_op(ASSET).set_timeout(60).build())
            tx.sign(kp)
            result["transactions"].append(server.submit_transaction(tx)["hash"])
        balance = Decimal(usdc["balance"]) if usdc else Decimal(0)
        if role == "cliente" and balance < 3 and args.fund_from:
            units = int((Decimal(3) - balance) * 10_000_000)
            proc = subprocess.run(["stellar", "tx", "new", "payment", "--source", args.fund_from,
                                   "--destination", kp.public_key, "--asset", f"{ASSET.code}:{ASSET.issuer}",
                                   "--amount", str(units), "--network", "testnet"], capture_output=True, text=True, encoding="utf-8")
            # No volcar salida de la CLI: solo extraer hashes de transacciones públicas.
            if proc.returncode:
                raise SystemExit("No se pudo fondear USDC con la identidad indicada; revisa su saldo de testnet.")
            hashes = re.findall(r"Signing transaction: ([0-9a-f]{64})", proc.stdout + proc.stderr)
            result["transactions"].extend(hashes)
        balances = request("GET", f"{HORIZON}/accounts/{kp.public_key}").json()["balances"]
        result["usdc"] = next((b["balance"] for b in balances if b.get("asset_code") == ASSET.code and b.get("asset_issuer") == ASSET.issuer), "0")
        result["ready"] = role == "programador" or Decimal(result["usdc"]) >= 3
        report["accounts"][role] = result
        print(f"{role}: {kp.public_key} · {result['usdc']} USDC · lista={result['ready']}")
    (ROOT / "docs/fases/fase-5-cuentas.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not all(x["ready"] for x in report["accounts"].values()):
        raise SystemExit("Faltan USDC de testnet: usa --fund-from IDENTIDAD o el faucet de Circle. Friendbot solo entrega XLM.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
