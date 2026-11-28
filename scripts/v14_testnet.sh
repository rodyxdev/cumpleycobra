#!/usr/bin/env bash
# Prueba en vivo en testnet de las 16 funciones nuevas de v14, dejando saldo y `held` en 0.
#
#   Bounty: open_bounty, top_up_bounty, award_bounty, refund_bounty
#   Retainer: create_retainer, release_retainer_cycle, refund_expired_retainer_cycle, cancel_retainer
#   Crowdfund: create_crowdfund_task, pledge_crowdfund_task, release_crowdfund_task, refund_crowdfund_task
#   Team + Cliff: deposit_team_task, release_team_task, refund_team_task, deposit_cliff_stream
#
# Uso: bash scripts/v14_testnet.sh [ID_DEL_CONTRATO_V14]
set -euo pipefail

V14="${1:-CCRL3UWLII45QQSXYNOFLR2MFUSNOLDZ3IW7YMU4FO4OXKGHUCVVFJJT}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V14" --source "$src" "${NET[@]}" -- "$@"; }
wait_until() { local t=$(( $1 - $(date +%s) )); if [ "$t" -gt 0 ]; then sleep "$t"; fi; }
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V14" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  local txh
  txh=$(stellar -q tx hash "${NET[@]}" "$xdr")
  echo "🔗 https://stellar.expert/explorer/testnet/tx/$txh"
  stellar tx send "${NET[@]}" "$xdr" >/dev/null
}

echo "== Contrato v14 $V14 · corrida $TS"
T0=$(date +%s)

B1="v14-b1-$TS"; B2="v14-b2-$TS"
R1="v14-r1-$TS"; R2="v14-r2-$TS"
C1="v14-c1-$TS"; C2="v14-c2-$TS"
T1="v14-t1-$TS"; T2="v14-t2-$TS"
S1="v14-s1-$TS"

echo "== 1. open_bounty (B2 plazo corto 45 s para refund) + B1 (600 s)"
call cyc-client open_bounty --client "$CLIENT" --bounty_id "$B2" --amount 10000 --deadline_secs 45 --rules_hash "$(sha b2)"
call cyc-client open_bounty --client "$CLIENT" --bounty_id "$B1" --amount 20000 --deadline_secs 600 --rules_hash "$(sha b1)"

echo "== 2. create_retainer R1 (2 ciclos x 25 s) y R2 (2 ciclos x 300 s)"
R1_START=$(date +%s)
call cyc-client create_retainer --client "$CLIENT" --retainer_id "$R1" --freelancer "$FREELANCER" --period_amount 10000 --period_secs 25 --cycles 2
echo "== release_retainer_cycle R1 ciclo 0"
call cyc-arbiter release_retainer_cycle --retainer_id "$R1" --deliverable_hash "$(sha r1c0)"
call cyc-client create_retainer --client "$CLIENT" --retainer_id "$R2" --freelancer "$FREELANCER" --period_amount 10000 --period_secs 300 --cycles 2

echo "== 3. create_crowdfund_task + pledge_crowdfund_task (C2 plazo 50 s para refund, C1 600 s)"
call cyc-client create_crowdfund_task --creator "$CLIENT" --task_id "$C2" --amount 10000 --deadline_secs 50 --rules_hash "$(sha c2)"
call cyc-third pledge_crowdfund_task --backer "$THIRD" --task_id "$C2" --amount 5000
call cyc-client create_crowdfund_task --creator "$CLIENT" --task_id "$C1" --amount 10000 --deadline_secs 600 --rules_hash "$(sha c1)"
call cyc-third pledge_crowdfund_task --backer "$THIRD" --task_id "$C1" --amount 5000

echo "== 4. deposit_team_task T2 (55 s para refund) y T1 (600 s)"
call cyc-client deposit_team_task --client "$CLIENT" --task_id "$T2" \
  --members "[\"$FREELANCER\",\"$THIRD\"]" --shares_bps '[7000,3000]' \
  --amount 20000 --deadline_secs 55 --rules_hash "$(sha t2)"
call cyc-client deposit_team_task --client "$CLIENT" --task_id "$T1" \
  --members "[\"$FREELANCER\",\"$THIRD\"]" --shares_bps '[7000,3000]' \
  --amount 20000 --deadline_secs 600 --rules_hash "$(sha t1)"

echo "== 5. top_up_bounty + award_bounty (2 ganadores en B1)"
call cyc-third top_up_bounty --funder "$THIRD" --bounty_id "$B1" --amount 5000
call cyc-arbiter award_bounty --bounty_id "$B1" --winner "$FREELANCER" --amount 15000 --proof_hash "$(sha w1)"
call cyc-arbiter award_bounty --bounty_id "$B1" --winner "$THIRD" --amount 10000 --proof_hash "$(sha w2)"

echo "== 6. release_crowdfund_task C1 + release_team_task T1"
call cyc-arbiter release_crowdfund_task --task_id "$C1" --freelancer "$FREELANCER" --code_hash "$(sha c1code)" --verdict_hash "$(sha c1v)"
call cyc-arbiter release_team_task --task_id "$T1" --code_hash "$(sha t1code)" --verdict_hash "$(sha t1v)"

echo "== 7. cancel_retainer R2 (cyc-client + cyc-freelancer)"
multi cyc-client "cyc-freelancer" -- cancel_retainer --retainer_id "$R2"

echo "== 8. deposit_cliff_stream S1 (cliff 5 s, 60 s)"
S1_START=$(date +%s)
call cyc-client deposit_cliff_stream --client "$CLIENT" --stream_id "$S1" --freelancer "$FREELANCER" --amount 20000 --cliff_secs 5 --duration_secs 60
wait_until $(( S1_START + 10 ))
call cyc-freelancer withdraw_stream --stream_id "$S1"
sleep 6
call cyc-client cancel_stream --stream_id "$S1"

echo "== 9. Reembolsos tras vencer plazos cortos (B2, R1 ciclo 1, C2, T2)"
wait_until $(( R1_START + 65 ))
echo "== refund_bounty B2"
call cyc-third refund_bounty --bounty_id "$B2"
echo "== refund_expired_retainer_cycle R1"
call cyc-third refund_expired_retainer_cycle --retainer_id "$R1"
echo "== refund_crowdfund_task C2"
call cyc-third refund_crowdfund_task --task_id "$C2"
echo "== refund_team_task T2"
call cyc-third refund_team_task --task_id "$T2"

echo "== Estado final: get_stats y saldo real USDC (los dos en 0)"
stellar contract invoke --id "$V14" --source cyc-client "${NET[@]}" --send=no -- get_stats
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V14"
