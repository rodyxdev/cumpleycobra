#!/usr/bin/env bash
# Prueba reproducible de la fase 1: backend FastAPI + contrato en testnet.
#
# Tarea 1: POST /tasks -> deposit (CLI) -> /accept -> /evaluate caso A = aprobado y pagado.
# Tarea 2: guardias (CRITERIA_NOT_ACCEPTED, TASK_NOT_FUNDED, INVALID_TOKEN, TASK_TAKEN),
#          B (llm, rechazo), C (security_flags), D (deterministic), reenvío de B = cache,
#          quinto envío distinto = 429.
# Tarea 3: plazo de 1 minuto -> DEADLINE_TOO_CLOSE sin contar el envío.
# Tarea 4: depósito con monto distinto al acordado -> TASK_MISMATCH.
# Reinicio del backend: las tareas siguen ahí y el reenvío de A es cache con el mismo hash.
# Al final espera a que venzan los plazos y hace timeout_refund de las tareas 2, 3 y 4.
#
# Requisitos: backend/.venv con requirements.txt, backend/.env, identidades cyc-* de la
# Stellar CLI y al menos 3.5 USDC en cyc-client (cada corrida gasta 1 USDC neto).
# Arranca y detiene el backend él mismo (puerto 8000).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=backend/.venv/Scripts/python
[ -x "$PY" ] || PY=backend/.venv/bin/python
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
API="http://127.0.0.1:8000"
NET="--network testnet"
CONTRACT_ID="$(grep -E '^CONTRACT_ID=' backend/.env | cut -d= -f2 | tr -d '\r')"
USDC="$(grep -E '^USDC_SAC_ID=' backend/.env | cut -d= -f2 | tr -d '\r')"
AMOUNT=10000000          # 1 USDC en unidades
DEADLINE_MIN=10          # plazo de la demo
LOGDIR=scripts/.logs
mkdir -p "$LOGDIR"

CLIENT="$(stellar keys public-key cyc-client)"
FREELANCER="$(stellar keys public-key cyc-freelancer)"
THIRD="$(stellar keys public-key cyc-third)"

u() { "$PY" scripts/fase1/util.py "$@"; }
j() { echo "$BODY" | u get "$1"; }

# --- backend ------------------------------------------------------------------
BACKEND_PID=""
start_backend() {
  "$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 >> "$LOGDIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  for _ in $(seq 1 40); do
    curl -sf "$API/health" > /dev/null 2>&1 && { echo "   backend arriba (pid $BACKEND_PID)"; return; }
    sleep 0.5
  done
  echo "ERROR: el backend no arrancó"; tail -20 "$LOGDIR/backend.log"; exit 1
}
stop_backend() {
  [ -n "$BACKEND_PID" ] || return 0
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  BACKEND_PID=""
}
trap stop_backend EXIT

# --- HTTP -----------------------------------------------------------------------
# req MÉTODO RUTA [CUERPO] [HEADER] -> $STATUS y $BODY
req() {
  local method=$1 path=$2 data=${3:-} hdr=${4:-}
  local args=(-s -o "$LOGDIR/resp.json" -w '%{http_code}' -X "$method" "$API$path")
  if [ -n "$data" ]; then  # el cuerpo va por archivo: en Windows los argumentos no son UTF-8
    printf '%s' "$data" > "$LOGDIR/req.json"
    args+=(-H 'Content-Type: application/json; charset=utf-8' --data-binary "@$LOGDIR/req.json")
  fi
  [ -n "$hdr" ] && args+=(-H "$hdr")
  echo "\$ curl -X $method $path${hdr:+ -H '${hdr%%:*}: …'}"
  STATUS="$(curl "${args[@]}")"
  BODY="$(cat "$LOGDIR/resp.json")"
  echo "   HTTP $STATUS"
  echo "$BODY" | u show
}
expect_status() { [ "$STATUS" = "$1" ] || { echo "FALLÓ: se esperaba HTTP $1"; exit 1; }; }
expect_error() {
  expect_status "$1"
  [ "$(j error)" = "$2" ] || { echo "FALLÓ: se esperaba error $2"; exit 1; }
  echo "   -> $1 $2 como se esperaba"
}
check() { [ "$1" = "$2" ] || { echo "FALLÓ: $3 (valor '$1', esperado '$2')"; exit 1; }; }

evaluate() { # evaluate TASK TOKEN ARCHIVO [DIRECCION] [SUFIJO]
  req POST /evaluate "$(u eval-body "$1" "${4:-$FREELANCER}" "$3" "${5:-}")" "X-Freelancer-Token: $2"
}

# --- Stellar CLI ------------------------------------------------------------------
LAST_TX=""
send() {
  local out
  out="$("$@" 2>&1)" || { echo "$out"; echo "FALLÓ: $*"; exit 1; }
  echo "$out" | grep -E "Signing transaction|Success - Event: [A-Za-z]+Event" | sed 's/^/   /'
  LAST_TX="$(echo "$out" | grep -oE 'Signing transaction: [0-9a-f]{64}' | tail -1 | awk '{print $3}')"
}
deposit() { # deposit TASK MONTO SEGUNDOS RULES_HASH
  echo "\$ stellar contract invoke … deposit --task_id $1 --amount $2 --deadline_secs $3"
  send stellar contract invoke --id "$CONTRACT_ID" --source cyc-client $NET -- \
    deposit --client cyc-client --task_id "\"$1\"" --amount "$2" --deadline_secs "$3" --rules_hash "$4"
}
balance() { stellar contract invoke --id "$USDC" --source cyc-arbiter $NET --send=no -- balance --id "$1" 2>/dev/null | tail -1; }
tx_ok() { curl -s "https://horizon-testnet.stellar.org/transactions/$1" | grep -oE '"successful": ?[a-z]+' | head -1; }

new_task() { # new_task MINUTOS -> TASK RULES INVITE CLIENT_TOKEN
  req POST /tasks "$(u task-body "$CLIENT" "$AMOUNT" "$1")"
  expect_status 200
  TASK="$(j task_id)"; RULES="$(j rules_hash)"; INVITE="$(j invite_token)"; CTOKEN="$(j client_token)"
}
accept() { # accept TASK INVITE [DIRECCION]
  req POST "/tasks/$1/accept" "$(u accept-body "${3:-$FREELANCER}" "$2")"
}

echo "== Arranque"
echo "   contrato $CONTRACT_ID"
echo "   USDC del cliente al inicio: $(balance "$CLIENT")"
start_backend
req GET /health; expect_status 200

# =====================================================================================
echo; echo "== Tarea 1: caso A aprobado y pagado"
new_task "$DEADLINE_MIN"; T1="$TASK"; RULES1="$RULES"; INV1="$INVITE"; CT1="$CTOKEN"
deposit "$T1" "$AMOUNT" $((DEADLINE_MIN * 60)) "$RULES1"; TX_DEP1="$LAST_TX"
accept "$T1" "$INV1"; expect_status 200; FT1="$(j freelancer_token)"
accept "$T1" "$INV1"; expect_status 200
check "$(j freelancer_token)" "$FT1" "/accept debe ser idempotente"
echo "   -> /accept idempotente: mismo freelancer_token"
evaluate "$T1" "$FT1" backend/casos/a_feliz.py
expect_status 200
check "$(j approved)" true "caso A aprobado"
check "$(j stage)" llm "caso A por Gemini"
TX_REL1="$(j transaction_hash)"; CH1="$(j code_hash)"
[ "$TX_REL1" != "null" ] || { echo "FALLÓ: sin transaction_hash"; exit 1; }
echo "   -> release en Horizon: $(tx_ok "$TX_REL1")"
req GET "/tasks/$T1"; expect_status 200
check "$(j onchain.status)" Released "tarea 1 Released on-chain"
check "$(j onchain.freelancer)" "$FREELANCER" "pagó al programador amarrado"
req GET "/tasks/$T1/delivery" "" "X-Client-Token: $CT1"; expect_status 200
check "$(j code_hash)" "$CH1" "el código entregado es el aprobado"
echo "   -> el cliente recibe el código tras el pago"

# =====================================================================================
echo; echo "== Tarea 2: guardias y casos B, C, D"
new_task "$DEADLINE_MIN"; T2="$TASK"; RULES2="$RULES"; INV2="$INVITE"
evaluate "$T2" "token-cualquiera" backend/casos/a_feliz.py
expect_error 409 CRITERIA_NOT_ACCEPTED
accept "$T2" "$INV2"; expect_status 200; FT2="$(j freelancer_token)"
evaluate "$T2" "$FT2" backend/casos/a_feliz.py
expect_error 409 TASK_NOT_FUNDED
deposit "$T2" "$AMOUNT" $((DEADLINE_MIN * 60)) "$RULES2"; TX_DEP2="$LAST_TX"

echo; echo "-- /evaluate con token equivocado (el de la tarea 1)"
evaluate "$T2" "$FT1" backend/casos/a_feliz.py
expect_error 403 INVALID_TOKEN
echo "-- /evaluate con el token correcto pero otra dirección"
evaluate "$T2" "$FT2" backend/casos/a_feliz.py "$THIRD"
expect_error 403 INVALID_TOKEN
echo "-- /accept de otra dirección con la misma invitación"
accept "$T2" "$INV2" "$THIRD"
expect_error 409 TASK_TAKEN

echo; echo "-- Caso B (calidad)"
evaluate "$T2" "$FT2" backend/casos/b_calidad.py; expect_status 200
check "$(j approved)" false "B rechazado"; check "$(j stage)" llm "B por Gemini"
check "$(j submissions_used)" 1 "B cuenta como envío 1"
echo "-- Caso C (inyección)"
evaluate "$T2" "$FT2" backend/casos/c_inyeccion.py; expect_status 200
check "$(j approved)" false "C rechazado"; check "$(j stage)" llm "C por Gemini"
[ "$(j security_flags)" != "[]" ] || { echo "FALLÓ: C sin security_flags"; exit 1; }
check "$(j submissions_used)" 2 "C cuenta como envío 2"
echo "-- Caso D (secretos)"
evaluate "$T2" "$FT2" backend/casos/d_secretos.py; expect_status 200
check "$(j approved)" false "D rechazado"; check "$(j stage)" deterministic "D determinista"
check "$(j submissions_used)" 3 "D cuenta como envío 3"
echo "-- Reenvío de B"
evaluate "$T2" "$FT2" backend/casos/b_calidad.py; expect_status 200
check "$(j stage)" cache "reenvío de B desde caché"
check "$(j submissions_used)" 3 "la caché no cuenta como envío"
echo "-- Quinto envío, código distinto"
evaluate "$T2" "$FT2" backend/casos/a_feliz.py "" $'\n# version 2\n'
expect_error 429 TOO_MANY_SUBMISSIONS

# =====================================================================================
echo; echo "== Tarea 3: plazo de 1 minuto (menos de 120 s)"
new_task 1; T3="$TASK"; RULES3="$RULES"; INV3="$INVITE"
accept "$T3" "$INV3"; expect_status 200; FT3="$(j freelancer_token)"
deposit "$T3" "$AMOUNT" 60 "$RULES3"; TX_DEP3="$LAST_TX"
evaluate "$T3" "$FT3" backend/casos/a_feliz.py
expect_error 409 DEADLINE_TOO_CLOSE
req GET "/tasks/$T3"; check "$(j submissions_used)" 0 "DEADLINE_TOO_CLOSE no cuenta como envío"

echo; echo "== Tarea 4: monto on-chain distinto al acordado"
new_task "$DEADLINE_MIN"; T4="$TASK"; RULES4="$RULES"; INV4="$INVITE"
accept "$T4" "$INV4"; expect_status 200; FT4="$(j freelancer_token)"
deposit "$T4" $((AMOUNT / 2)) 300 "$RULES4"; TX_DEP4="$LAST_TX"
evaluate "$T4" "$FT4" backend/casos/a_feliz.py
expect_error 409 TASK_MISMATCH

# =====================================================================================
echo; echo "== Reinicio del backend"
stop_backend
echo "   backend detenido"
start_backend
req GET "/tasks/$T1"; expect_status 200
check "$(j onchain.status)" Released "tarea 1 tras reinicio"
req GET "/tasks/$T2"; expect_status 200
check "$(j submissions_used)" 3 "envíos de la tarea 2 tras reinicio"
echo "-- Reenvío de A en la tarea 1 tras el reinicio"
evaluate "$T1" "$FT1" backend/casos/a_feliz.py; expect_status 200
check "$(j stage)" cache "A desde caché tras reinicio"
check "$(j transaction_hash)" "$TX_REL1" "mismo transaction_hash"

# =====================================================================================
echo; echo "== timeout_refund de las tareas 2, 3 y 4"
while :; do
  req GET "/tasks/$T2" > /dev/null
  LEFT="$(j seconds_left)"
  [ "$LEFT" != "null" ] && [ "$LEFT" -lt -5 ] && break
  echo "   plazo de la tarea 2: quedan ${LEFT} s; esperando…"
  sleep 30
done
REFUNDS=()
for T in "$T3" "$T4" "$T2"; do
  echo "\$ stellar contract invoke --source cyc-third … timeout_refund --task_id $T"
  send stellar contract invoke --id "$CONTRACT_ID" --source cyc-third $NET -- timeout_refund --task_id "\"$T\""
  REFUNDS+=("$T $LAST_TX")
done
req GET "/tasks/$T2"; check "$(j onchain.status)" Refunded "tarea 2 reembolsada"

echo; echo "== Saldos USDC al final"
echo "   cliente:    $(balance "$CLIENT")"
echo "   freelancer: $(balance "$FREELANCER")"
echo "   contrato:   $(balance "$CONTRACT_ID")"

echo; echo "== Resumen"
echo "tarea 1: $T1  deposit $TX_DEP1  release $TX_REL1"
echo "tarea 2: $T2  deposit $TX_DEP2"
echo "tarea 3: $T3  deposit $TX_DEP3"
echo "tarea 4: $T4  deposit $TX_DEP4"
for r in "${REFUNDS[@]}"; do echo "timeout_refund: $r"; done
echo "OK: fase 1 completa"
