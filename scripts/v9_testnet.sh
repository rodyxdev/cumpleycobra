#!/usr/bin/env bash
# Prueba en testnet de las 4 funciones nuevas del contrato v9, con firmas reales
# (reassign_stream lleva tres) y montos pequeños de USDC. Deja el contrato en 0.
#
#   top_up_stream, reassign_stream, slash_bond_partial y release_with_fee.
#
# Uso: bash scripts/v9_testnet.sh [ID_DEL_CONTRATO_V9]
set -euo pipefail

V9="${1:-CBFH6QNU5JPG3GL2EKHRQVQASYHEODHJGSH6COOC2WVCRW5GNYAUFSY7}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V9" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V9" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}

S1="v9-s1-$TS"; TA="v9-ta-$TS"; TB="v9-tb-$TS"
echo "== Contrato v9 $V9 · corrida $TS"

echo "== 0. deposit_stream (cyc-client): 0.02 USDC para cyc-freelancer en 300 s"
START=$(date +%s)
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 200000 --duration_secs 300

echo "== 1. top_up_stream (cyc-client): +0.01 USDC; el final se recorre 150 s"
call cyc-client top_up_stream --stream_id "$S1" --amount 100000

echo "== 2. reassign_stream (cyc-client + cyc-freelancer + cyc-third) a los ~40 s"
wait_until $(( START + 40 ))
multi cyc-client "cyc-freelancer cyc-third" -- reassign_stream --stream_id "$S1" --new_freelancer "$THIRD"

echo "== -  cancel_stream (cyc-client) a los ~70 s para cerrar: lo ganado a cyc-third, el resto al cliente"
wait_until $(( START + 70 ))
call cyc-client cancel_stream --stream_id "$S1"

echo "== 3. slash_bond_partial (cyc-arbiter): garantía de 0.01 repartida 0.004 / 0.006"
TA_START=$(date +%s)
call cyc-client deposit --client "$CLIENT" --task_id "$TA" --amount 200000 --deadline_secs 60 --rules_hash "$(sha "$TA")"
call cyc-arbiter assign_freelancer --task_id "$TA" --freelancer "$FREELANCER"
call cyc-freelancer post_bond --task_id "$TA" --amount 100000
wait_until $(( TA_START + 75 ))
call cyc-client timeout_refund --task_id "$TA"
call cyc-arbiter slash_bond_partial --task_id "$TA" --client_amount 40000

echo "== 4. release_with_fee (cyc-arbiter): 0.02 con 10% de comisión para cyc-third"
call cyc-client deposit --client "$CLIENT" --task_id "$TB" --amount 200000 --deadline_secs 600 --rules_hash "$(sha "$TB")"
call cyc-arbiter release_with_fee --task_id "$TB" --freelancer "$FREELANCER" \
  --code_hash "$(sha 'v9 codigo')" --verdict_hash "$(sha 'v9 veredicto')" --fee_to "$THIRD" --fee_bps 1000

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V9" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V9"
