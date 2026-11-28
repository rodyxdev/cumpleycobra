#!/usr/bin/env bash
# Prueba en testnet de las 3 funciones nuevas del contrato v13, con firmas reales
# (transfer_stream_client lleva tres) y montos pequeños de USDC. Deja el contrato en 0.
#
#   top_up_bond, release_milestone_with_fee y transfer_stream_client.
#
# Uso: bash scripts/v13_testnet.sh [ID_DEL_CONTRATO_V13]
set -euo pipefail

V13="${1:-CANNTLUPTRTAGLEDJS5R5NHLYPQFHEOUKXCOY3H3DF77IGZM37WEIFHF}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V13" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V13" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}


T1="v13-t1-$TS"; T2="v13-t2-$TS"; P1="v13-p1-$TS"; P2="v13-p2-$TS"; P3="v13-p3-$TS"; S1="v13-s1-$TS"
echo "== Contrato v13 $V13 · corrida $TS"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P2" --amounts '["100000","100000"]' --deadlines_secs '[5,5]' --rules_hashes "[\"$(sha p2a)\",\"$(sha p2b)\"]"
call cyc-client deposit --client "$CLIENT" --task_id "$T1" --amount 100000 --deadline_secs 600 --rules_hash "$(sha "$T1")"
echo "== contribute_task"; call cyc-third contribute_task --funder "$THIRD" --task_id "$T1" --amount 10000
echo "== client_release_with_fee"; call cyc-client client_release_with_fee --task_id "$T1" --freelancer "$FREELANCER" --fee_to "$THIRD" --fee_bps 1000
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" --amounts '["100000","100000"]' --deadlines_secs '[600,600]' --rules_hashes "[\"$(sha p1a)\",\"$(sha p1b)\"]"
echo "== contribute_milestone"; call cyc-third contribute_milestone --funder "$THIRD" --task_id "$P1" --index 1 --amount 10000
echo "== client_release_milestone_fee"; call cyc-client client_release_milestone_fee --task_id "$P1" --index 0 --freelancer "$FREELANCER" --fee_to "$THIRD" --fee_bps 1000
echo "== extend_project_deadlines"; call cyc-client extend_project_deadlines --task_id "$P1" --extra_secs 60
echo "== post_project_bond + top_up_project_bond"; call cyc-freelancer post_project_bond --task_id "$P1" --amount 10000
call cyc-freelancer top_up_project_bond --task_id "$P1" --amount 10000
echo "== mutual_split_project"; multi cyc-client "cyc-freelancer" -- mutual_split_project --task_id "$P1" --freelancer_amount 50000
call cyc-freelancer reclaim_project_bond --task_id "$P1"
echo "== refund_expired_projects_batch"; call cyc-third refund_expired_projects_batch --task_ids "[\"$P2\",\"no-existe-$TS\"]"
call cyc-client deposit_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 100000 --duration_secs 600
sleep 8
echo "== contribute_stream"; call cyc-third contribute_stream --funder "$THIRD" --stream_id "$S1" --amount 10000
sleep 8
echo "== withdraw_stream_to"; call cyc-freelancer withdraw_stream_to --stream_id "$S1" --to "$THIRD"
sleep 8
call cyc-client cancel_stream --stream_id "$S1"
stellar contract invoke --id "$V13" --source cyc-client "${NET[@]}" --send=no -- get_stats
