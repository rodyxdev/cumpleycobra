#!/usr/bin/env bash
# Prueba de la fase 0 en testnet desde la Stellar CLI.
#
# Tarea A: deposit -> release falso (debe fallar) -> release del árbitro -> doble release (debe fallar)
# Tarea B: deposit con plazo corto -> timeout_refund antes de tiempo (debe fallar)
#          -> espera el plazo -> timeout_refund disparado por un tercero
# Tarea C: deposit con plazo corto -> espera el plazo -> release del árbitro
#          (debe fallar con DeadlinePassed = #9) -> timeout_refund
#
# Requisitos: identidades cyc-arbiter, cyc-client, cyc-freelancer y cyc-third
# (ver contracts/cumpleycobra/README.md) y al menos 3 USDC de testnet en cyc-client.
# Cada corrida gasta 1 USDC neto (el que cobra el freelancer en la tarea A).
set -euo pipefail

NET="--network testnet"
ID="${CONTRACT_ID:-CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ}"
USDC="${USDC_SAC_ID:-CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA}"
AMOUNT="${AMOUNT:-10000000}"          # 1 USDC en unidades (7 decimales)
SHORT_DEADLINE="${SHORT_DEADLINE:-30}" # segundos para las tareas B y C
RUN="$(date +%s)"
TASK_A="fase0-a-$RUN"
TASK_B="fase0-b-$RUN"
TASK_C="fase0-c-$RUN"

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

# Ejecuta algo que DEBE fallar con un Error(Contract, #N) concreto.
must_fail_code() {
  local code="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "$out"; echo "ERROR: esta llamada debía fallar: $*"; exit 1
  fi
  echo "$out" | grep -E 'Error\(' | head -2
  echo "$out" | grep -qF "Error(Contract, #$code)" || { echo "ERROR: se esperaba Error(Contract, #$code)"; exit 1; }
  echo "   -> falló con #$code como se esperaba"
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

# --- Tarea A: pago normal ----------------------------------------------------
echo; echo "== Tarea A ($TASK_A): deposit con plazo de 600 s"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  deposit --client cyc-client --task_id "\"$TASK_A\"" --amount "$AMOUNT" \
  --deadline_secs 600 --rules_hash "$RULES_HASH"
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
must_fail_code 6 stellar contract invoke --id "$ID" --source cyc-arbiter $NET -- \
  release --task_id "\"$TASK_A\"" --freelancer cyc-freelancer \
  --code_hash "$CODE_HASH" --verdict_hash "$VERDICT_HASH"

echo; echo "== Saldos tras la tarea A"; balances

# --- Tareas B y C: plazo corto -----------------------------------------------
echo; echo "== Tarea B ($TASK_B): deposit con plazo de $SHORT_DEADLINE s"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  deposit --client cyc-client --task_id "\"$TASK_B\"" --amount "$AMOUNT" \
  --deadline_secs "$SHORT_DEADLINE" --rules_hash "$RULES_HASH"
TX_DEPOSIT_B="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_B\""

echo; echo "== Tarea B: timeout_refund antes del plazo (debe fallar con DeadlineNotReached = #7)"
must_fail_code 7 stellar contract invoke --id "$ID" --source cyc-third $NET -- \
  timeout_refund --task_id "\"$TASK_B\""

echo; echo "== Tarea C ($TASK_C): deposit con plazo de $SHORT_DEADLINE s"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  deposit --client cyc-client --task_id "\"$TASK_C\"" --amount "$AMOUNT" \
  --deadline_secs "$SHORT_DEADLINE" --rules_hash "$RULES_HASH"
TX_DEPOSIT_C="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_C\""

echo; echo "== Saldos con B y C depositadas"; balances

TERCERO_ANTES="$(read_only "$USDC" balance --id cyc-third)"
echo; echo "== Esperando $((SHORT_DEADLINE + 20)) s a que venzan los plazos de B y C…"
sleep $((SHORT_DEADLINE + 20))

echo; echo "== Tarea C: release del árbitro después del plazo (debe fallar con DeadlinePassed = #9)"
must_fail_code 9 stellar contract invoke --id "$ID" --source cyc-arbiter $NET -- \
  release --task_id "\"$TASK_C\"" --freelancer cyc-freelancer \
  --code_hash "$CODE_HASH" --verdict_hash "$VERDICT_HASH"

echo; echo "== Tarea C: timeout_refund"
send stellar contract invoke --id "$ID" --source cyc-client $NET -- \
  timeout_refund --task_id "\"$TASK_C\""
TX_REFUND_C="$LAST_TX"
read_only "$ID" get_task --task_id "\"$TASK_C\""

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
echo "deposit A:        $TX_DEPOSIT_A"
echo "release A:        $TX_RELEASE_A"
echo "deposit B:        $TX_DEPOSIT_B"
echo "timeout_refund B: $TX_REFUND_B"
echo "deposit C:        $TX_DEPOSIT_C"
echo "timeout_refund C: $TX_REFUND_C"
