#!/usr/bin/env bash
# Proyecto de prueba en testnet sobre el contrato v3 (docs/hitos/diseno.md).
#
# Recorre el flujo completo con las dos funciones nuevas de v3:
#   1. deposit_milestones  cyc-client  deposita 2 hitos de 0.2 + 0.2 USDC (plazos de 120 s)
#   2. add_milestone       cyc-client  agrega un 3.º hito de 0.1 USDC (plazo de 120 s)
#   3. top_up_milestone    cyc-client  aumenta el hito 0 en +0.1 USDC (pasa a 0.3 USDC)
#   4. release_milestone   cyc-arbiter libera los 3 hitos (0.3 + 0.2 + 0.1 = 0.6 USDC)
# y al final lee el proyecto con get_project.
#
# Los hashes de criterios, código y veredicto son SHA-256 de textos de ejemplo: en esta etapa el
# backend todavía no verifica hitos (etapa 2).
#
# Uso: bash scripts/hitos_v3_testnet.sh ID_DEL_CONTRATO_V3
set -euo pipefail

V3="${1:?Uso: bash scripts/hitos_v3_testnet.sh ID_DEL_CONTRATO_V3}"
NET=(--network testnet)
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
TASK="hitos-v3-$(date +%s)"
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

echo "== Contrato v3 $V3 · proyecto $TASK"
echo "== 1. deposit_milestones (cliente): 2 hitos de 0.2 y 0.2 USDC, plazos de 120 s"
stellar contract invoke --id "$V3" --source cyc-client "${NET[@]}" -- deposit_milestones \
  --client "$CLIENT" --task_id "$TASK" \
  --amounts '["2000000","2000000"]' \
  --deadlines_secs '[120,120]' \
  --rules_hashes "[\"$(sha 'hito 0: estructura')\",\"$(sha 'hito 1: logica')\"]"

echo "== 2. add_milestone (cliente): 3.º hito de 0.1 USDC, plazo de 120 s"
stellar contract invoke --id "$V3" --source cyc-client "${NET[@]}" -- add_milestone \
  --task_id "$TASK" --amount 1000000 --deadline_secs 120 \
  --rules_hash "$(sha 'hito 2: pruebas')"

echo "== 3. top_up_milestone (cliente): aumento de +0.1 USDC al hito 0"
stellar contract invoke --id "$V3" --source cyc-client "${NET[@]}" -- top_up_milestone \
  --task_id "$TASK" --index 0 --amount 1000000

for i in 0 1 2; do
  echo "== 4.$((i + 1)). release_milestone (árbitro): hito $i al programador"
  stellar contract invoke --id "$V3" --source cyc-arbiter "${NET[@]}" -- release_milestone \
    --task_id "$TASK" --index "$i" --freelancer "$FREELANCER" \
    --code_hash "$(sha "codigo hito $i")" --verdict_hash "$(sha "veredicto hito $i")"
done

echo "== get_project"
stellar contract invoke --id "$V3" --source cyc-client "${NET[@]}" --send=no -- get_project --task_id "$TASK"
