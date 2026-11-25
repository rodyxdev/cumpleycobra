#!/usr/bin/env bash
# Proyecto real de 3 hitos en testnet sobre el contrato v2 (docs/hitos/diseno.md).
#
# Usa las cuatro funciones nuevas, cada una con la identidad que le corresponde:
#   1. deposit_milestones        cyc-client  deposita 0.3 + 0.3 + 0.2 USDC de una vez
#   2. release_milestone         cyc-arbiter paga el hito 0 al programador
#   3. client_release_milestone  cyc-client  aprueba a mano el hito 1
#   4. timeout_refund_milestone  cyc-third   (un tercero) dispara el reembolso del hito 2 vencido
# y al final lee el proyecto con get_project.
#
# Los hashes de criterios, código y veredicto son SHA-256 de textos de ejemplo: en esta etapa el
# backend todavía no verifica hitos (etapa 2). Los plazos son cortos (90 s) para poder mostrar el
# reembolso en la misma corrida.
#
# Uso: bash scripts/hitos_testnet.sh [ID_DEL_CONTRATO_V2]
set -euo pipefail

V2="${1:-CAUBTDTWJKWKXH25LHXPES3ADTDRMBHYK4VOSWEWIBIYNLUINDR2K77K}"
NET=(--network testnet)
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
TASK="hitos-$(date +%s)"
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

echo "== Contrato v2 $V2 · proyecto $TASK"
echo "== 1. deposit_milestones (cliente): 3 hitos de 0.3, 0.3 y 0.2 USDC, plazos de 90 s"
stellar contract invoke --id "$V2" --source cyc-client "${NET[@]}" -- deposit_milestones \
  --client "$CLIENT" --task_id "$TASK" \
  --amounts '["3000000","3000000","2000000"]' \
  --deadlines_secs '[90,90,90]' \
  --rules_hashes "[\"$(sha 'hito 0: estructura')\",\"$(sha 'hito 1: logica')\",\"$(sha 'hito 2: pruebas')\"]"

echo "== 2. release_milestone (árbitro): hito 0 al programador"
stellar contract invoke --id "$V2" --source cyc-arbiter "${NET[@]}" -- release_milestone \
  --task_id "$TASK" --index 0 --freelancer "$FREELANCER" \
  --code_hash "$(sha 'codigo hito 0')" --verdict_hash "$(sha 'veredicto hito 0')"

echo "== 3. client_release_milestone (cliente): aprobación manual del hito 1"
stellar contract invoke --id "$V2" --source cyc-client "${NET[@]}" -- client_release_milestone \
  --task_id "$TASK" --index 1 --freelancer "$FREELANCER"

echo "== Espera a que venza el plazo del hito 2 (90 s desde el depósito)"
sleep 95

echo "== 4. timeout_refund_milestone (un tercero): el hito 2 vuelve al cliente"
stellar contract invoke --id "$V2" --source cyc-third "${NET[@]}" -- timeout_refund_milestone \
  --task_id "$TASK" --index 2

echo "== get_project"
stellar contract invoke --id "$V2" --source cyc-client "${NET[@]}" --send=no -- get_project --task_id "$TASK"
