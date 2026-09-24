#!/usr/bin/env bash
# Fondea una wallet de la demo (por ejemplo, la wallet de Pollar del cliente) con USDC de testnet.
#
# Uso: bash scripts/fondear.sh DIRECCION_G MONTO_USDC [IDENTIDAD]
#   MONTO_USDC: en USDC, con hasta 7 decimales (ej. 2 o 1.5)
#   IDENTIDAD: identidad de la Stellar CLI que paga (por defecto cyc-client)
#
# Requisitos: la wallet destino ya existe en testnet y ya activó USDC (botón "Activar USDC" de la app).
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Uso: bash scripts/fondear.sh DIRECCION_G MONTO_USDC [IDENTIDAD]" >&2
  exit 2
fi
DEST="$1"; MONTO="$2"; SOURCE="${3:-cyc-client}"
USDC_ASSET="${USDC_ASSET:-USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5}"
HORIZON="https://horizon-testnet.stellar.org"

[[ "$DEST" =~ ^G[A-Z2-7]{55}$ ]] || { echo "Dirección inválida: $DEST" >&2; exit 2; }
[[ "$MONTO" =~ ^[0-9]+(\.[0-9]{1,7})?$ ]] || { echo "Monto inválido: $MONTO (usa USDC, ej. 2 o 1.5)" >&2; exit 2; }

# USDC -> unidades (7 decimales) sin float: se separan entero y decimales.
ENTERO="${MONTO%%.*}"; DECIMALES=""
[[ "$MONTO" == *.* ]] && DECIMALES="${MONTO#*.}"
DECIMALES="$(printf '%-7s' "$DECIMALES" | tr ' ' 0)"
UNIDADES="$((10#$ENTERO * 10000000 + 10#$DECIMALES))"

CUENTA="$(curl -s "$HORIZON/accounts/$DEST")"
if echo "$CUENTA" | grep -q '"status": 404'; then
  echo "La cuenta $DEST no existe en testnet. Iníciala desde la app (Pollar) antes de fondearla." >&2
  exit 1
fi
if ! echo "$CUENTA" | grep -q "\"asset_issuer\": \"${USDC_ASSET#*:}\""; then
  echo "La cuenta $DEST no tiene trustline de USDC. Pulsa \"Activar USDC\" en la app primero." >&2
  exit 1
fi

echo "Enviando $MONTO USDC ($UNIDADES unidades) de $SOURCE a $DEST"
out="$(stellar tx new payment --source "$SOURCE" --destination "$DEST" --asset "$USDC_ASSET" \
  --amount "$UNIDADES" --network testnet 2>&1)" || { echo "$out"; exit 1; }
tx="$(echo "$out" | grep -oE 'Signing transaction: [0-9a-f]{64}' | tail -1 | awk '{print $3}')"
echo "Transacción: $tx"
echo "https://stellar.expert/explorer/testnet/tx/$tx"
