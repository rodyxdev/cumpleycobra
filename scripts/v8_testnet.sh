#!/usr/bin/env bash
# Prueba en testnet de las 6 funciones nuevas del contrato v8, con firmas reales
# y montos pequeños de USDC. Deja el contrato en saldo 0.
#
#   Pago por tiempo: deposit_stream, withdraw_stream, cancel_stream.
#   Garantía del programador: post_bond, reclaim_bond, slash_bond.
#
# Uso: bash scripts/v8_testnet.sh [ID_DEL_CONTRATO_V8]
set -euo pipefail

V8="${1:-CB3VPJSLGWIAO3LQNZETWFF6UHO5OYEQ33HTLV3FFJMNZVJHW67O4AKZ}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V8" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }

S1="v8-s1-$TS"
TA="v8-ta-$TS"
TB="v8-tb-$TS"
echo "== Contrato v8 $V8 · corrida $TS"

echo "== 1. deposit_stream (cyc-client): 0.02 USDC para cyc-freelancer durante 120 s"
START=$(date +%s)
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" \
  --amount 200000 --duration_secs 120

echo "== 2. withdraw_stream (cyc-freelancer) a los ~40 s: retira lo liberado"
wait_until $(( START + 40 ))
call cyc-freelancer withdraw_stream --stream_id "$S1"

echo "== 3. cancel_stream (cyc-client) a los ~80 s: lo ganado al programador, el resto al cliente"
wait_until $(( START + 80 ))
call cyc-client cancel_stream --stream_id "$S1"

echo "== 4. post_bond (cyc-freelancer): garantía de 0.005 sobre $TA (0.01, 600 s)"
call cyc-client deposit --client "$CLIENT" --task_id "$TA" --amount 100000 --deadline_secs 600 --rules_hash "$(sha "$TA")"
call cyc-arbiter assign_freelancer --task_id "$TA" --freelancer "$FREELANCER"
call cyc-freelancer post_bond --task_id "$TA" --amount 50000

echo "== 5. reclaim_bond (cyc-freelancer): la tarea se paga y la garantía vuelve"
call cyc-client client_release --task_id "$TA" --freelancer "$FREELANCER"
call cyc-freelancer reclaim_bond --task_id "$TA"

echo "== 6. slash_bond (cyc-arbiter): $TB vence sin entrega, se reembolsa y la garantía pasa al cliente"
TB_START=$(date +%s)
call cyc-client deposit --client "$CLIENT" --task_id "$TB" --amount 100000 --deadline_secs 60 --rules_hash "$(sha "$TB")"
call cyc-arbiter assign_freelancer --task_id "$TB" --freelancer "$FREELANCER"
call cyc-freelancer post_bond --task_id "$TB" --amount 50000
wait_until $(( TB_START + 75 ))
call cyc-client timeout_refund --task_id "$TB"
call cyc-arbiter slash_bond --task_id "$TB"

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V8" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V8"
