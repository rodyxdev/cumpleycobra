#!/usr/bin/env bash
# Prueba en testnet de las 3 funciones nuevas del contrato v10, con firmas reales
# (transfer_stream_client lleva tres) y montos pequeños de USDC. Deja el contrato en 0.
#
#   top_up_bond, release_milestone_with_fee y transfer_stream_client.
#
# Uso: bash scripts/v10_testnet.sh [ID_DEL_CONTRATO_V10]
set -euo pipefail

V10="${1:-CDNYUAAS6KLJOBCAHGB7DWQOKIPC6AWGRCDXTUIYERMP5ZQZE7UH7W3H}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V10" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V10" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}

TA="v10-ta-$TS"; P1="v10-p1-$TS"; S1="v10-s1-$TS"
echo "== Contrato v10 $V10 · corrida $TS"

echo "== 1. top_up_bond (cyc-freelancer): garantía 0.005 + 0.005 sobre $TA"
call cyc-client deposit --client "$CLIENT" --task_id "$TA" --amount 200000 --deadline_secs 600 --rules_hash "$(sha "$TA")"
call cyc-arbiter assign_freelancer --task_id "$TA" --freelancer "$FREELANCER"
call cyc-freelancer post_bond --task_id "$TA" --amount 50000
call cyc-freelancer top_up_bond --task_id "$TA" --amount 50000
echo "== -  cierre: client_release y reclaim_bond (la garantía completa, 0.01, vuelve)"
call cyc-client client_release --task_id "$TA" --freelancer "$FREELANCER"
call cyc-freelancer reclaim_bond --task_id "$TA"

echo "== 2. release_milestone_with_fee (cyc-arbiter): hito 0 de 0.01 con 10% para cyc-third"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" \
  --amounts '["100000","100000"]' --deadlines_secs '[600,600]' \
  --rules_hashes "[\"$(sha 'v10 p1 h0')\",\"$(sha 'v10 p1 h1')\"]"
call cyc-arbiter release_milestone_with_fee --task_id "$P1" --index 0 --freelancer "$FREELANCER" \
  --code_hash "$(sha 'v10 codigo')" --verdict_hash "$(sha 'v10 veredicto')" --fee_to "$THIRD" --fee_bps 1000
call cyc-client client_release_milestone --task_id "$P1" --index 1 --freelancer "$FREELANCER"

echo "== 3. transfer_stream_client (cyc-client + cyc-third + cyc-freelancer): el pago pasa a cyc-third"
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 200000 --duration_secs 300
multi cyc-client "cyc-third cyc-freelancer" -- transfer_stream_client --stream_id "$S1" --new_client "$THIRD"
echo "== -  cierre: cancel_stream del cliente nuevo"
call cyc-third cancel_stream --stream_id "$S1"

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V10" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V10"
