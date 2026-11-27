#!/usr/bin/env bash
# Prueba completa en testnet de las 11 funciones nuevas del contrato v4.
#
# Recorre en vivo cada función nueva con firmas reales (incluyendo doble firma
# Soroban mediante `scripts/sign_soroban_auth.py` y `stellar tx send`), usando
# montos pequeños de USDC y dejando el contrato en saldo 0 y con `cyc-arbiter`
# restaurado al final:
#   1. batch_deposit                 (cyc-client)
#   2. mutual_split_task             (cyc-client + cyc-freelancer)
#   3. cancel_unassigned_task        (cyc-client + cyc-arbiter)
#   4. client_release_with_bonus     (cyc-client)
#   5. cancel_unassigned_project     (cyc-client + cyc-arbiter)
#   6. reduce_milestone              (cyc-client + cyc-arbiter)
#   7. split_milestone               (cyc-client)
#   8. extend_milestone_deadline     (cyc-client)
#   9. mutual_split_milestone        (cyc-client + cyc-freelancer)
#  10. rotate_arbiter                (cyc-arbiter + cyc-third, y vuelta a cyc-arbiter)
#  11. refund_all_expired_milestones (cyc-third, sin permisos)
#
# Uso: bash scripts/hitos_v4_testnet.sh [ID_DEL_CONTRATO_V4]
set -euo pipefail

V4="${1:-CBZ6TBVTNYOWGEFCSUGPO4GRWRNW4YAY6SK222XECEVVIIXFLD6TFK2E}"
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
ARBITER=$(stellar keys public-key cyc-arbiter)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# Invoca una función con doble firma Soroban (source + co-firmante).
invoke_dual() {
  local src="$1"
  local cosigner="$2"
  shift 2
  local xdr
  xdr=$(stellar -q contract invoke --id "$V4" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  xdr=$("$PY" scripts/sign_soroban_auth.py "$cosigner" "$xdr")
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}

echo "== Contrato v4 $V4 · corrida $TS"

TA="v4-ta-$TS"
TB="v4-tb-$TS"
TC="v4-tc-$TS"
P1="v4-p1-$TS"
P2="v4-p2-$TS"

echo "== 1. batch_deposit (cyc-client): 3 tareas (0.03 + 0.02 + 0.02 = 0.07 USDC)"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- batch_deposit \
  --client "$CLIENT" \
  --task_ids "[\"$TA\",\"$TB\",\"$TC\"]" \
  --amounts '["300000","200000","200000"]' \
  --deadlines_secs '[300,300,300]' \
  --rules_hashes "[\"$(sha 'tarea A')\",\"$(sha 'tarea B')\",\"$(sha 'tarea C')\"]"

echo "== 2. mutual_split_task (cyc-client + cyc-freelancer): $TA -> 0.01 al programador, 0.02 al cliente"
invoke_dual cyc-client cyc-freelancer mutual_split_task \
  --task_id "$TA" --freelancer "$FREELANCER" --freelancer_amount 100000

echo "== 3. cancel_unassigned_task (cyc-client + cyc-arbiter): cancela $TB y devuelve 0.02 al cliente"
invoke_dual cyc-client cyc-arbiter cancel_unassigned_task \
  --task_id "$TB"

echo "== 4. client_release_with_bonus (cyc-client): aprueba $TC (0.02) + bono 0.005 al programador"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- client_release_with_bonus \
  --task_id "$TC" --freelancer "$FREELANCER" --bonus 50000

echo "== 5a. deposit_milestones para $P1 (0.02 + 0.02 USDC)"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- deposit_milestones \
  --client "$CLIENT" --task_id "$P1" \
  --amounts '["200000","200000"]' \
  --deadlines_secs '[300,300]' \
  --rules_hashes "[\"$(sha 'p1 h0')\",\"$(sha 'p1 h1')\"]"

echo "== 5b. cancel_unassigned_project (cyc-client + cyc-arbiter): cancela $P1 y devuelve 0.04 al cliente"
invoke_dual cyc-client cyc-arbiter cancel_unassigned_project \
  --task_id "$P1"

echo "== 6a. deposit_milestones para $P2 (0.03 a 55 s + 0.04 a 125 s)"
T0=$(date +%s)
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- deposit_milestones \
  --client "$CLIENT" --task_id "$P2" \
  --amounts '["300000","400000"]' \
  --deadlines_secs '[55,125]' \
  --rules_hashes "[\"$(sha 'p2 h0')\",\"$(sha 'p2 h1')\"]"

echo "== 6b. reduce_milestone (cyc-client + cyc-arbiter): recorta hito 0 en 0.01 (0.03 -> 0.02)"
invoke_dual cyc-client cyc-arbiter reduce_milestone \
  --task_id "$P2" --index 0 --reduce_amount 100000

echo "== 7. split_milestone (cyc-client): divide hito 1 (0.04) en 0.02 + 0.02"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- split_milestone \
  --task_id "$P2" --index 1 --first_amount 200000 --first_deadline_secs 55 \
  --first_rules_hash "$(sha 'p2 h1 parte 1')" --second_rules_hash "$(sha 'p2 h1 parte 2')"

echo "== 8. extend_milestone_deadline (cyc-client): prorroga hito 0 en +10 s"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" -- extend_milestone_deadline \
  --task_id "$P2" --index 0 --extra_secs 10

echo "== 9. mutual_split_milestone (cyc-client + cyc-freelancer): hito 0 -> 0.01 al programador, 0.01 al cliente"
invoke_dual cyc-client cyc-freelancer mutual_split_milestone \
  --task_id "$P2" --index 0 --freelancer "$FREELANCER" --freelancer_amount 100000

echo "== 10a. rotate_arbiter (cyc-arbiter + cyc-third): rota árbitro a cyc-third"
invoke_dual cyc-arbiter cyc-third rotate_arbiter --new_arbiter "$THIRD"

echo "== 10b. rotate_arbiter (cyc-third + cyc-arbiter): restaura árbitro a cyc-arbiter"
invoke_dual cyc-third cyc-arbiter rotate_arbiter --new_arbiter "$ARBITER"

# Esperar a que venzan los hitos 1 y 2 de P2 (T0 + 140 s) antes del reembolso en lote.
NOW=$(date +%s)
TARGET=$((T0 + 140))
if [ "$NOW" -lt "$TARGET" ]; then
  WAIT=$((TARGET - NOW))
  echo "== Esperando ${WAIT}s para que venzan los hitos 1 y 2 de $P2..."
  sleep "$WAIT"
fi

echo "== 11. refund_all_expired_milestones (cyc-third, sin permisos): reembolsa hitos 1 y 2 (0.04 USDC)"
stellar contract invoke --id "$V4" --source cyc-third "${NET[@]}" -- refund_all_expired_milestones \
  --task_id "$P2"

echo "== Estado final: get_project $P2 y get_config"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" --send=no -- get_project --task_id "$P2"
stellar contract invoke --id "$V4" --source cyc-client "${NET[@]}" --send=no -- get_config
