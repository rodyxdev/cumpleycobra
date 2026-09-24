#!/usr/bin/env bash
# Depósito de una tarea desde la Stellar CLI (mientras Pollar no firma en el navegador).
#
# Uso: bash scripts/deposit.sh TASK_ID MONTO_UNIDADES PLAZO_SEGUNDOS RULES_HASH [IDENTIDAD]
#   MONTO_UNIDADES: entero, 1 USDC = 10000000
#   IDENTIDAD: identidad de la Stellar CLI que deposita (por defecto cyc-client)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 4 ]; then
  echo "Uso: bash scripts/deposit.sh TASK_ID MONTO_UNIDADES PLAZO_SEGUNDOS RULES_HASH [IDENTIDAD]" >&2
  exit 2
fi
TASK_ID="$1"; AMOUNT="$2"; DEADLINE_SECS="$3"; RULES_HASH="$4"; SOURCE="${5:-cyc-client}"
CONTRACT_ID="${CONTRACT_ID:-$(grep -E '^CONTRACT_ID=' backend/.env | cut -d= -f2 | tr -d '\r')}"

echo "Depositando $AMOUNT unidades en la tarea $TASK_ID (plazo $DEADLINE_SECS s) desde $SOURCE"
out="$(stellar contract invoke --id "$CONTRACT_ID" --source "$SOURCE" --network testnet -- \
  deposit --client "$SOURCE" --task_id "\"$TASK_ID\"" --amount "$AMOUNT" \
  --deadline_secs "$DEADLINE_SECS" --rules_hash "$RULES_HASH" 2>&1)" || { echo "$out"; exit 1; }
echo "$out" | grep -E "Success - Event: DepositEvent|error" || true
tx="$(echo "$out" | grep -oE 'Signing transaction: [0-9a-f]{64}' | tail -1 | awk '{print $3}')"
echo "Transacción: $tx"
echo "https://stellar.expert/explorer/testnet/tx/$tx"
