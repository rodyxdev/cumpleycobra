#!/usr/bin/env bash
# Prueba en testnet de las 6 funciones nuevas del contrato v12, con firmas reales
# (cada parte firma lo suyo) y montos pequeños de USDC. Deja el contrato en 0.
#
#   client_release_partial, client_release_milestone_partial, post_project_bond,
#   reclaim_project_bond, slash_project_bond y withdraw_stream_batch.
#
# Uso: bash scripts/v12_testnet.sh [ID_DEL_CONTRATO_V12]
set -euo pipefail

V12="${1:-CAIPLT3HJ23N7UT56Q5XT5VNGDOCKMZOVXLI3CYGRBDJQLBNMF2YCJHH}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V12" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V12" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}


TA="v12-ta-$TS"; P1="v12-p1-$TS"; P2="v12-p2-$TS"; S1="v12-s1-$TS"; S2="v12-s2-$TS"
echo "== Contrato v12 $V12 · corrida $TS"
P2_START=$(date +%s)
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P2" --amounts '["100000","100000"]' --deadlines_secs '[90,90]' \
  --rules_hashes "[\"$(sha 'v12 p2 h0')\",\"$(sha 'v12 p2 h1')\"]"
call cyc-arbiter assign_project_freelancer --task_id "$P2" --freelancer "$FREELANCER"
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 100000 --duration_secs 600
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S2" --freelancer "$FREELANCER" --amount 100000 --duration_secs 600

echo "== 1. client_release_partial (cyc-client): 0.01 de una tarea de 0.03"
call cyc-client deposit --client "$CLIENT" --task_id "$TA" --amount 300000 --deadline_secs 600 --rules_hash "$(sha "$TA")"
call cyc-arbiter assign_freelancer --task_id "$TA" --freelancer "$FREELANCER"
call cyc-client client_release_partial --task_id "$TA" --freelancer "$FREELANCER" --amount 100000
call cyc-client client_release --task_id "$TA" --freelancer "$FREELANCER"

echo "== 2. client_release_milestone_partial (cyc-client): 0.01 del hito 0 (0.02)"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" --amounts '["200000","100000"]' --deadlines_secs '[600,600]' \
  --rules_hashes "[\"$(sha 'v12 p1 h0')\",\"$(sha 'v12 p1 h1')\"]"
call cyc-client client_release_milestone_partial --task_id "$P1" --index 0 --freelancer "$FREELANCER" --amount 100000

echo "== 3. post_project_bond (cyc-freelancer): garantía de 0.005 sobre $P1"
call cyc-freelancer post_project_bond --task_id "$P1" --amount 50000
call cyc-client client_release_milestone --task_id "$P1" --index 0 --freelancer "$FREELANCER"
call cyc-client client_release_milestone --task_id "$P1" --index 1 --freelancer "$FREELANCER"
echo "== 4. reclaim_project_bond (cyc-freelancer): proyecto pagado, la garantía vuelve"
call cyc-freelancer reclaim_project_bond --task_id "$P1"

echo "== 5. withdraw_stream_batch (cyc-freelancer): retira de $S1 y $S2 a la vez"
call cyc-freelancer withdraw_stream_batch --freelancer "$FREELANCER" --stream_ids "[\"$S1\",\"$S2\"]"
# Tras el retiro, se espera a que el programador gane algo para que la simulación incluya su pago.
sleep 8
call cyc-client cancel_stream_batch --client "$CLIENT" --stream_ids "[\"$S1\",\"$S2\"]"

echo "== 6. slash_project_bond (cyc-arbiter): $P2 vence sin entrega; de la garantía 0.005, 0.002 al cliente"
call cyc-freelancer post_project_bond --task_id "$P2" --amount 50000
wait_until $(( P2_START + 105 ))
call cyc-client refund_all_expired_milestones --task_id "$P2"
call cyc-arbiter slash_project_bond --task_id "$P2" --client_amount 20000

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V12" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V12"
