#!/usr/bin/env bash
# Prueba en testnet de las 14 funciones nuevas del contrato v6, con firmas reales
# (hasta tres por transacción) y montos pequeños de USDC. Deja el contrato en
# saldo 0 y los depósitos sin pausa.
#
#   deposit_assigned, amend_rules, release_partial, open_dispute, get_dispute,
#   resolve_dispute, tip, reassign_freelancer, transfer_client, mutual_cancel,
#   bump_ttl, pause, unpause y get_stats.
#
# Uso: bash scripts/v6_testnet.sh [ID_DEL_CONTRATO_V6]
set -euo pipefail

V6="${1:-CD5ZI4KIEUT4QI46SJHVRORDQXLTRBFGJTRJQ5SZI2WMJVYTBKN5TABU}"
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
NET=(--network testnet)
PY="${PYTHON:-backend/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="python3"; fi
CLIENT=$(stellar keys public-key cyc-client)
FREELANCER=$(stellar keys public-key cyc-freelancer)
THIRD=$(stellar keys public-key cyc-third)
TS=$(date +%s)
sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
call() { local src="$1"; shift; stellar contract invoke --id "$V6" --source "$src" "${NET[@]}" -- "$@"; }
# Lectura enviada como transacción (deja un hash en el explorador).
read_tx() { stellar contract invoke --id "$V6" --source cyc-client "${NET[@]}" --send=yes -- "$@"; }

# Invoca con varias firmas Soroban: `src` firma la transacción y cada co-firmante
# su entrada de autorización. Uso: multi SRC "COFIRMANTE1 COFIRMANTE2" -- función args…
multi() {
  local src="$1" cosigners="$2"
  shift 3
  local xdr
  xdr=$(stellar -q contract invoke --id "$V6" --source "$src" "${NET[@]}" --build-only -- "$@")
  xdr=$(stellar -q tx simulate --source-account "$src" "${NET[@]}" "$xdr")
  for c in $cosigners; do
    xdr=$("$PY" scripts/sign_soroban_auth.py "$c" "$xdr")
  done
  xdr=$(stellar -q tx sign --sign-with-key "$src" "${NET[@]}" "$xdr")
  stellar tx send "${NET[@]}" "$xdr" | grep -o '"txHash":"[0-9a-f]*"\|"hash":"[0-9a-f]*"' | head -1 || true
}

T1="v6-t1-$TS"
T2="v6-t2-$TS"
echo "== Contrato v6 $V6 · corrida $TS"

echo "== 1. deposit_assigned (cyc-client + cyc-freelancer): $T1, 0.03 USDC, 600 s"
multi cyc-client "cyc-freelancer" -- deposit_assigned --client "$CLIENT" --task_id "$T1" \
  --amount 300000 --deadline_secs 600 --rules_hash "$(sha 'v6 t1 criterios')" --freelancer "$FREELANCER"

echo "== 2. amend_rules (cyc-client + cyc-freelancer): criterios nuevos para $T1"
multi cyc-client "cyc-freelancer" -- amend_rules --task_id "$T1" --new_rules_hash "$(sha 'v6 t1 criterios v2')"

echo "== 3. release_partial (cyc-arbiter): 0.01 al programador, quedan 0.02"
call cyc-arbiter release_partial --task_id "$T1" --amount 100000 \
  --code_hash "$(sha 'v6 codigo parcial')" --verdict_hash "$(sha 'v6 veredicto parcial')"

echo "== 4. open_dispute (cyc-freelancer) sobre $T1"
call cyc-freelancer open_dispute --task_id "$T1" --by "$FREELANCER"

echo "== 5. get_dispute (lectura enviada como transacción)"
read_tx get_dispute --task_id "$T1"

echo "== 6. resolve_dispute (cyc-arbiter): 0.01 al programador y 0.01 de vuelta al cliente"
call cyc-arbiter resolve_dispute --task_id "$T1" --freelancer_amount 100000

echo "== 7. tip (cyc-client): propina de 0.005 sobre $T1 ya pagada"
call cyc-client tip --task_id "$T1" --amount 50000

echo "== 8. deposit + assign_freelancer de $T2 (0.02 USDC)"
call cyc-client deposit --client "$CLIENT" --task_id "$T2" --amount 200000 --deadline_secs 600 --rules_hash "$(sha 'v6 t2')"
call cyc-arbiter assign_freelancer --task_id "$T2" --freelancer "$FREELANCER"

echo "== 9. reassign_freelancer (cyc-client + cyc-freelancer + cyc-third): $T2 pasa a cyc-third"
multi cyc-client "cyc-freelancer cyc-third" -- reassign_freelancer --task_id "$T2" --new_freelancer "$THIRD"

echo "== 10. transfer_client (cyc-client + cyc-freelancer como cliente nuevo + cyc-third): $T2 cambia de cliente"
multi cyc-client "cyc-freelancer cyc-third" -- transfer_client --task_id "$T2" --new_client "$FREELANCER"

echo "== 11. mutual_cancel (cliente nuevo + cyc-third): el depósito de $T2 vuelve al cliente nuevo"
multi cyc-freelancer "cyc-third" -- mutual_cancel --task_id "$T2"

echo "== 12. bump_ttl (cyc-third, sin permisos) sobre $T1"
# La CLI lo ve como lectura si la vida ya está extendida: se fuerza el envío.
stellar contract invoke --id "$V6" --source cyc-third "${NET[@]}" --send=yes -- bump_ttl --task_id "$T1"

echo "== 13. pause (cyc-arbiter); un depósito en pausa debe fallar con Paused (#20); unpause"
call cyc-arbiter pause
if call cyc-client deposit --client "$CLIENT" --task_id "v6-pausa-$TS" --amount 100000 --deadline_secs 600 \
  --rules_hash "$(sha 'pausa')" 2>/tmp/v6_pausa.txt; then
  echo "ERROR: el contrato aceptó un depósito en pausa" >&2
  exit 1
fi
grep -o "Error(Contract, #20)" /tmp/v6_pausa.txt | head -1
call cyc-arbiter unpause

echo "== 14. get_stats (lectura enviada como transacción): held debe ser 0"
read_tx get_stats

echo "== Saldo real del contrato en USDC (debe ser 0)"
stellar contract invoke --id "$USDC" --source cyc-client "${NET[@]}" --send=no -- balance --id "$V6"
