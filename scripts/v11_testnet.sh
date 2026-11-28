#!/usr/bin/env bash
# Prueba en testnet de las 10 funciones nuevas del contrato v11, con firmas reales
# (los acuerdos llevan dos) y montos pequeños de USDC. Deja el contrato en 0.
#
#   extend_stream, reduce_stream, tip_stream, open_stream_dispute, resolve_stream_dispute, mutual_split_stream,
#   batch_deposit_streams, cancel_stream_batch, release_milestones_batch y tip_project.
#
# Uso: bash scripts/v11_testnet.sh [ID_DEL_CONTRATO_V11]
set -euo pipefail

V11="${1:-CANTD5BFSEWIAXPQ4HZZMXUZADBS3PIIEUNNMRSPZW55JJNIZCLSKJXY}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V11" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V11" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}


S1="v11-s1-$TS"; S2="v11-s2-$TS"; S3="v11-s3-$TS"; S4="v11-s4-$TS"; P1="v11-p1-$TS"
echo "== Contrato v11 $V11 · corrida $TS"
START=$(date +%s)
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 200000 --duration_secs 600
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S2" --freelancer "$FREELANCER" --amount 200000 --duration_secs 600
wait_until $(( START + 25 ))
echo "== 1. extend_stream (cyc-client + cyc-freelancer): +300 s a $S1"
multi cyc-client "cyc-freelancer" -- extend_stream --stream_id "$S1" --extra_secs 300
# Tras extend_stream el pago se reinicia desde ahora: se espera a que el programador gane algo para que
# la simulación incluya su pago (si no, el pago real queda fuera del footprint).
sleep 8
echo "== 2. reduce_stream (cyc-client + cyc-freelancer): 0.005 de lo pendiente vuelve al cliente"
multi cyc-client "cyc-freelancer" -- reduce_stream --stream_id "$S1" --reduce_amount 50000
# tip_stream exige que el programador ya haya ganado algo desde el último cambio del pago.
sleep 8
echo "== 3. tip_stream (cyc-client): propina de 0.001"
call cyc-client tip_stream --stream_id "$S1" --amount 10000
echo "== 4. open_stream_dispute (cyc-freelancer)"
call cyc-freelancer open_stream_dispute --stream_id "$S1" --by "$FREELANCER"
echo "== 5. resolve_stream_dispute (cyc-arbiter): 0.002 de lo pendiente al programador, el resto al cliente"
call cyc-arbiter resolve_stream_dispute --stream_id "$S1" --freelancer_amount 20000
echo "== 6. mutual_split_stream (cyc-client + cyc-freelancer) sobre $S2: 0.005 de lo pendiente al programador"
multi cyc-client "cyc-freelancer" -- mutual_split_stream --stream_id "$S2" --freelancer_amount 50000
echo "== 7. batch_deposit_streams (cyc-client): $S3 y $S4 (0.01 cada uno)"
call cyc-client batch_deposit_streams --client "$CLIENT" --stream_ids "[\"$S3\",\"$S4\"]" \
  --freelancers "[\"$FREELANCER\",\"$THIRD\"]" --amounts '["100000","100000"]' --durations_secs '[600,600]'
sleep 10
echo "== 8. cancel_stream_batch (cyc-client): cancela los dos"
call cyc-client cancel_stream_batch --client "$CLIENT" --stream_ids "[\"$S3\",\"$S4\",\"no-existe-$TS\"]"
echo "== 9. release_milestones_batch (cyc-arbiter): dos hitos de $P1 en una transacción"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" \
  --amounts '["100000","100000"]' --deadlines_secs '[600,600]' \
  --rules_hashes "[\"$(sha 'v11 p1 h0')\",\"$(sha 'v11 p1 h1')\"]"
call cyc-arbiter release_milestones_batch --task_id "$P1" --indices '[0,1]' --freelancer "$FREELANCER" \
  --code_hashes "[\"$(sha 'c0')\",\"$(sha 'c1')\"]" --verdict_hashes "[\"$(sha 'v0')\",\"$(sha 'v1')\"]"
echo "== 10. tip_project (cyc-client): propina de 0.001 sobre $P1"
call cyc-client tip_project --task_id "$P1" --amount 10000

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V11" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V11"
