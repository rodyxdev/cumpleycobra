#!/usr/bin/env bash
# Prueba en testnet de las 6 funciones nuevas del contrato v5, con firmas reales
# y montos pequeños de USDC. Deja el contrato en saldo 0.
#   1. assign_freelancer          (cyc-arbiter)
#   2. extend_deadline            (cyc-client)
#   3. top_up_task                (cyc-client)
#   -  client_release a otra dirección: el contrato la rechaza (WrongFreelancer)
#   4. freelancer_refund          (cyc-freelancer)
#   5. assign_project_freelancer  (cyc-arbiter)
#   6. get_tasks                  (lectura, sin firma)
#
# Uso: bash scripts/v5_testnet.sh [ID_DEL_CONTRATO_V5]
set -euo pipefail

V5="${1:-CDWVPFHQJGBHI7DJQDFGYAHWRQKNDHIESFKO3MSUD6NPS7AKDYKUZEXM}"
NET=(--network testnet)
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V5" --source "$src" "${NET[@]}" -- "$@"; }

TA="v5-ta-$TS"
TB="v5-tb-$TS"
P1="v5-p1-$TS"

echo "== Contrato v5 $V5 · corrida $TS"

echo "== 0. deposit $TA (0.02 USDC, 600 s) y $TB (0.01 USDC, 600 s)"
call cyc-client deposit --client "$CLIENT" --task_id "$TA" --amount 200000 --deadline_secs 600 --rules_hash "$(sha 'v5 tarea A')"
call cyc-client deposit --client "$CLIENT" --task_id "$TB" --amount 100000 --deadline_secs 600 --rules_hash "$(sha 'v5 tarea B')"

echo "== 1. assign_freelancer (cyc-arbiter): $TA y $TB quedan amarradas a cyc-freelancer"
call cyc-arbiter assign_freelancer --task_id "$TA" --freelancer "$FREELANCER"
call cyc-arbiter assign_freelancer --task_id "$TB" --freelancer "$FREELANCER"

echo "== 2. extend_deadline (cyc-client): +300 s a $TA"
call cyc-client extend_deadline --task_id "$TA" --extra_secs 300

echo "== 3. top_up_task (cyc-client): +0.01 USDC a $TA (queda en 0.03)"
call cyc-client top_up_task --task_id "$TA" --amount 100000

echo "== -  client_release de $TA hacia el propio cliente: debe fallar con WrongFreelancer (#12)"
if call cyc-client client_release --task_id "$TA" --freelancer "$CLIENT" 2>/tmp/v5_wrong.txt; then
  echo "ERROR: el contrato aceptó pagarle a otra dirección" >&2
  exit 1
fi
grep -o "Error(Contract, #12)" /tmp/v5_wrong.txt | head -1

echo "== -  client_release de $TA al programador registrado (0.03 USDC)"
call cyc-client client_release --task_id "$TA" --freelancer "$FREELANCER"

echo "== 4. freelancer_refund (cyc-freelancer): renuncia a $TB y el cliente recupera 0.01"
call cyc-freelancer freelancer_refund --task_id "$TB"

echo "== 5. assign_project_freelancer (cyc-arbiter) sobre un proyecto de 2 hitos (0.01 + 0.01)"
call cyc-client deposit_milestones --client "$CLIENT" --task_id "$P1" \
  --amounts '["100000","100000"]' --deadlines_secs '[600,600]' \
  --rules_hashes "[\"$(sha 'v5 p1 h0')\",\"$(sha 'v5 p1 h1')\"]"
call cyc-arbiter assign_project_freelancer --task_id "$P1" --freelancer "$FREELANCER"
call cyc-client client_release_milestone --task_id "$P1" --index 0 --freelancer "$FREELANCER"
call cyc-client client_release_milestone --task_id "$P1" --index 1 --freelancer "$FREELANCER"

echo "== 6. get_tasks (lectura por lote): $TA, $TB y un task_id que no existe"
stellar contract invoke --id "$V5" --source cyc-client "${NET[@]}" --send=no -- get_tasks \
  --task_ids "[\"$TA\",\"$TB\",\"no-existe-$TS\"]"

echo "== Saldo final del contrato (debe ser 0)"
stellar contract invoke --id CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA --source cyc-client "${NET[@]}" --send=no -- \
  balance --id "$V5"
