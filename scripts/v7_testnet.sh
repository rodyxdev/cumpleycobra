#!/usr/bin/env bash
# Prueba en testnet de las 13 funciones nuevas del contrato v7, con firmas reales
# (hasta tres por transacción) y montos pequeños de USDC. Deja el contrato en 0.
#
#   amend_milestone_rules, release_milestone_partial, open_milestone_dispute,
#   get_milestone_dispute, cancel_milestone_dispute, resolve_milestone_dispute,
#   reassign_project_freelancer, transfer_project_client, mutual_cancel_project,
#   release_batch, cancel_dispute, refund_batch y get_projects.
#
# Uso: bash scripts/v7_testnet.sh [ID_DEL_CONTRATO_V7]
set -euo pipefail

V7="${1:-CCTEXF2IQTD6KXNC64TKM3GEDU56KQ6QRCO4B2UYQBWIZ6AGRU3JAHDM}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V7" --source "$src" "${NET[@]}" -- "$@"; }
read_tx() { stellar contract invoke --id "$V7" --source cyc-client "${NET[@]}" --send=yes -- "$@"; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V7" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}

P1="v7-p1-$TS"
T1="v7-t1-$TS"; T2="v7-t2-$TS"; T3="v7-t3-$TS"; T4="v7-t4-$TS"
echo "== Contrato v7 $V7 · corrida $TS"

echo "== 0. Proyecto $P1 (0.02 + 0.02, 600 s y 900 s) con programador fijado"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" \
  --amounts '["200000","200000"]' --deadlines_secs '[600,900]' \
  --rules_hashes "[\"$(sha 'v7 p1 h0')\",\"$(sha 'v7 p1 h1')\"]"
call cyc-arbiter assign_project_freelancer --task_id "$P1" --freelancer "$FREELANCER"

echo "== 1. amend_milestone_rules (cyc-client + cyc-freelancer): hito 0"
multi cyc-client "cyc-freelancer" -- amend_milestone_rules --task_id "$P1" --index 0 --new_rules_hash "$(sha 'v7 p1 h0 v2')"

echo "== 2. release_milestone_partial (cyc-arbiter): 0.01 del hito 0"
call cyc-arbiter release_milestone_partial --task_id "$P1" --index 0 --amount 100000 \
  --code_hash "$(sha 'v7 codigo')" --verdict_hash "$(sha 'v7 veredicto')"

echo "== 3. open_milestone_dispute (cyc-client) sobre el hito 1"
call cyc-client open_milestone_dispute --task_id "$P1" --index 1 --by "$CLIENT"

echo "== 4. get_milestone_dispute (lectura enviada como transacción)"
read_tx get_milestone_dispute --task_id "$P1" --index 1

echo "== 5. cancel_milestone_dispute (cyc-client): retira la disputa del hito 1"
call cyc-client cancel_milestone_dispute --task_id "$P1" --index 1

echo "== 6. open_milestone_dispute (cyc-freelancer) sobre el hito 0 y resolve_milestone_dispute (cyc-arbiter): 0.005 / 0.005"
call cyc-freelancer open_milestone_dispute --task_id "$P1" --index 0 --by "$FREELANCER"
call cyc-arbiter resolve_milestone_dispute --task_id "$P1" --index 0 --freelancer_amount 50000

echo "== 7. reassign_project_freelancer (cyc-client + cyc-freelancer + cyc-third)"
multi cyc-client "cyc-freelancer cyc-third" -- reassign_project_freelancer --task_id "$P1" --new_freelancer "$THIRD"

echo "== 8. transfer_project_client (cyc-client + cyc-freelancer como cliente nuevo + cyc-third)"
multi cyc-client "cyc-freelancer cyc-third" -- transfer_project_client --task_id "$P1" --new_client "$FREELANCER"

echo "== 9. mutual_cancel_project (cliente nuevo + cyc-third): el hito 1 (0.02) vuelve al cliente nuevo"
multi cyc-freelancer "cyc-third" -- mutual_cancel_project --task_id "$P1"

echo "== 10. release_batch (cyc-arbiter): $T1 y $T2 (0.01 cada una) en una transacción"
for t in "$T1" "$T2"; do
  call cyc-client deposit --client "$CLIENT" --task_id "$t" --amount 100000 --deadline_secs 600 --rules_hash "$(sha "$t")"
  call cyc-arbiter assign_freelancer --task_id "$t" --freelancer "$FREELANCER"
done
call cyc-arbiter release_batch --task_ids "[\"$T1\",\"$T2\"]" \
  --code_hashes "[\"$(sha 'c1')\",\"$(sha 'c2')\"]" --verdict_hashes "[\"$(sha 'v1')\",\"$(sha 'v2')\"]"

echo "== 11. cancel_dispute (cyc-client): $T4 con disputa abierta y retirada"
START=$(date +%s)
call cyc-client deposit --client "$CLIENT" --task_id "$T3" --amount 100000 --deadline_secs 90 --rules_hash "$(sha "$T3")"
call cyc-client deposit --client "$CLIENT" --task_id "$T4" --amount 100000 --deadline_secs 90 --rules_hash "$(sha "$T4")"
call cyc-arbiter assign_freelancer --task_id "$T4" --freelancer "$FREELANCER"
call cyc-client open_dispute --task_id "$T4" --by "$CLIENT"
call cyc-client cancel_dispute --task_id "$T4"

echo "== 12. refund_batch (cyc-third, sin permisos): $T3 y $T4 al vencer"
WAIT=$(( START + 110 - $(date +%s) ))
if [ "$WAIT" -gt 0 ]; then sleep "$WAIT"; fi
call cyc-third refund_batch --task_ids "[\"$T3\",\"$T4\",\"no-existe-$TS\"]"

echo "== 13. get_projects (lectura enviada como transacción)"
read_tx get_projects --task_ids "[\"$P1\",\"no-existe-$TS\"]"

echo "== get_stats y saldo real del contrato (los dos en 0)"
stellar contract invoke --id "$V7" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V7"
