#!/usr/bin/env bash
# Prueba en testnet de las 3 funciones nuevas del contrato v15, con firmas reales
# (transfer_stream_client lleva tres) y montos pequeños de USDC. Deja el contrato en 0.
#
#   top_up_bond, release_milestone_with_fee y transfer_stream_client.
#
# Uso: bash scripts/v15_testnet.sh [ID_DEL_CONTRATO_V15]
set -euo pipefail

V15="${1:-CAQUWYA5IWT7KF4GFCHTMX7F5XT3JSSPG2OS7EFAIT4ZNUDXYS62V3BC}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V15" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V15" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}


dep() { call cyc-client deposit --client "$CLIENT" --task_id "$1" --amount 100000 --deadline_secs 600 --rules_hash "$(sha "$1")" >/dev/null; }
A="v15-a-$TS"; B="v15-b-$TS"; C="v15-c-$TS"; D="v15-d-$TS"; E="v15-e-$TS"; F="v15-f-$TS"; P="v15-p-$TS"
echo "== Contrato v15 $V15 · corrida $TS"
for t in "$A" "$B" "$C" "$D" "$E" "$F"; do dep "$t"; done
echo "== extend_deadlines_batch"; call cyc-client extend_deadlines_batch --client "$CLIENT" --task_ids "[\"$A\",\"$B\"]" --extra_secs 60
echo "== top_up_tasks_batch"; call cyc-client top_up_tasks_batch --client "$CLIENT" --task_ids "[\"$A\",\"$B\"]" --amounts '["10000","10000"]'
for t in "$A" "$B"; do call cyc-arbiter assign_freelancer --task_id "$t" --freelancer "$FREELANCER" >/dev/null; call cyc-freelancer post_bond --task_id "$t" --amount 10000 >/dev/null; done
echo "== client_release_batch"; call cyc-client client_release_batch --client "$CLIENT" --task_ids "[\"$A\",\"$B\"]" --freelancers "[\"$FREELANCER\",\"$FREELANCER\"]"
echo "== reclaim_bonds_batch"; call cyc-freelancer reclaim_bonds_batch --freelancer "$FREELANCER" --task_ids "[\"$A\",\"$B\"]"
echo "== cancel_unassigned_tasks_batch"; multi cyc-client "cyc-arbiter" -- cancel_unassigned_tasks_batch --client "$CLIENT" --task_ids "[\"$C\",\"$D\"]"
call cyc-client client_release_batch --client "$CLIENT" --task_ids "[\"$E\",\"$F\"]" --freelancers "[\"$FREELANCER\",\"$FREELANCER\"]" >/dev/null
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P" --amounts '["100000","100000"]' --deadlines_secs '[600,600]' --rules_hashes "[\"$(sha pa)\",\"$(sha pb)\"]" >/dev/null
echo "== client_release_milestones_batch"; call cyc-client client_release_milestones_batch --task_id "$P" --indices '[0,1]' --freelancer "$FREELANCER"
stellar contract invoke --id "$V15" --source cyc-client "${NET[@]}" --send=no -- get_stats
