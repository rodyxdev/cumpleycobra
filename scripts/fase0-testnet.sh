#!/usr/bin/env bash
# Prueba de la fase 0 en testnet desde la Stellar CLI.
#
# Tarea A: deposit -> release falso (debe fallar) -> release del árbitro -> doble release (debe fallar)
# Tarea B: deposit con plazo corto -> timeout_refund antes de tiempo (debe fallar)
#          -> espera el plazo -> timeout_refund disparado por un tercero
#
# Requisitos: identidades cyc-arbiter, cyc-client, cyc-freelancer y cyc-third
# (ver contracts/cumpleycobra/README.md) y al menos 2 USDC de testnet en cyc-client.
set -euo pipefail

NET="--network testnet"
ID="${CONTRACT_ID:-CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND}"
USDC="${USDC_SAC_ID:-CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA}"
AMOUNT="${AMOUNT:-10000000}"          # 1 USDC en unidades (7 decimales)
SHORT_DEADLINE="${SHORT_DEADLINE:-30}" # segundos para la tarea B
RUN="$(date +%s)"
TASK_A="fase0-a-$RUN"
TASK_B="fase0-b-$RUN"

# Hashes de ejemplo (SHA-256 en hexadecimal; en el contrato viajan como BytesN<32>).
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
RULES_HASH="$(sha "criterios-fase0-$RUN")"
CODE_HASH="$(sha "codigo-fase0-$RUN")"
VERDICT_HASH="$(sha "veredicto-fase0-$RUN")"

# Ejecuta una transacción, muestra la salida y guarda su hash en $LAST_TX.
LAST_TX=""
send() {
  local out
  out="$("$@" 2>&1)" || { echo "$out"; echo "FALLÓ: $*"; exit 1; }
  echo "$out"
  LAST_TX="$(echo "$out" | grep -oE 'Signing transaction: [0-9a-f]{64}' | tail -1 | awk '{print $3}')"
}

# Ejecuta algo que DEBE fallar; si no falla, aborta.
must_fail() {
  local out
  if out="$("$@" 2>&1)"; then
    echo "$out"; echo "ERROR: esta llamada debía fallar: $*"; exit 1
  fi
  echo "$out" | grep -E 'Error\(|error' | head -3
  echo "   -> falló como se esperaba"
}

read_only() { stellar contract invoke --id "$1" --source cyc-arbiter $NET --send=no -- "${@:2}" 2>/dev/null | tail -1; }
balances() {
  echo "   cliente:    $(read_only "$USDC" balance --id cyc-client)"
  echo "   contrato:   $(read_only "$USDC" balance --id "$ID")"
  echo "   freelancer: $(read_only "$USDC" balance --id cyc-freelancer)"
  echo "   tercero:    $(read_only "$USDC" balance --id cyc-third)"
}

echo "== Contrato $ID | USDC $USDC | monto $AMOUNT"
echo "== Saldos iniciales"; balances

echo; echo "== Tarea A ($TASK_A): deposit"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  deposit --client cyc-client --task_id "\"$TASK_A\"" --amount "$AMOUNT" \
  --deadline_secs 300 --rules_hash "$RULES_HASH"
TX_DEPOSIT_A="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_A\""

echo; echo "== Tarea A: release firmado por un árbitro falso (cyc-third)"
must_fail stellar contract invoke --id "$ID" --source cyc-third $NET -- \
  release --task_id "\"$TASK_A\"" --freelancer cyc-freelancer \
  --code_hash "$CODE_HASH" --verdict_hash "$VERDICT_HASH"

echo; echo "== Tarea A: release del árbitro"
send stellar contract invoke --id "$ID" --source cyc-arbiter $NET -- \
  release --task_id "\"$TASK_A\"" --freelancer cyc-freelancer \
  --code_hash "$CODE_HASH" --verdict_hash "$VERDICT_HASH"
TX_RELEASE_A="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_A\""

echo; echo "== Tarea A: segundo release (debe fallar con NotFunded = #6)"
must_fail stellar contract invoke --id "$ID" --source cyc-arbiter $NET -- \
  release --task_id "\"$TASK_A\"" --freelancer cyc-freelancer \
  --code_hash "$CODE_HASH" --verdict_hash "$VERDICT_HASH"

echo; echo "== Saldos tras la tarea A"; balances

echo; echo "== Tarea B ($TASK_B): deposit con plazo de $SHORT_DEADLINE s"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  deposit --client cyc-client --task_id "\"$TASK_B\"" --amount "$AMOUNT" \
  --deadline_secs "$SHORT_DEADLINE" --rules_hash "$RULES_HASH"
TX_DEPOSIT_B="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_B\""

echo; echo "== Tarea B: timeout_refund antes del plazo (debe fallar con DeadlineNotReached = #7)"
must_fail stellar contract invoke --id "$ID" --source cyc-third $NET -- \
  timeout_refund --task_id "\"$TASK_B\""

TERCERO_ANTES="$(read_only "$USDC" balance --id cyc-third)"
echo; echo "== Esperando $((SHORT_DEADLINE + 15)) s a que venza el plazo…"
sleep $((SHORT_DEADLINE + 15))

echo; echo "== Tarea B: timeout_refund disparado por un tercero (cyc-third)"
send stellar contract invoke --id "$ID" --source cyc-third $NET -- \
  timeout_refund --task_id "\"$TASK_B\""
TX_REFUND_B="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_B\""
TERCERO_DESPUES="$(read_only "$USDC" balance --id cyc-third)"
echo "   USDC del tercero antes: $TERCERO_ANTES, después: $TERCERO_DESPUES"
[ "$TERCERO_ANTES" = "$TERCERO_DESPUES" ] || { echo "ERROR: cambió el saldo del tercero"; exit 1; }

echo; echo "== Saldos finales"; balances

echo; echo "== Resumen"
echo "rules_hash:   $RULES_HASH"
echo "code_hash:    $CODE_HASH"
echo "verdict_hash: $VERDICT_HASH"
echo "deposit A:      $TX_DEPOSIT_A"
echo "release A:      $TX_RELEASE_A"
echo "deposit B:      $TX_DEPOSIT_B"
echo "timeout_refund: $TX_REFUND_B"
