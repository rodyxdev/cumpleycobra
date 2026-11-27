#!/usr/bin/env bash
# Despliegue EXPERIMENTAL del contrato en mainnet (misión especial de Ship It).
#
# Gasta XLM reales (unos 25 XLM entre subir el código e initialize). Antes:
#   1. La cuenta del árbitro de mainnet (identidad `cyc-mainnet-arbiter`, guardada en el
#      almacén seguro del sistema; distinta de la de testnet) debe tener al menos 30 XLM.
#   2. `cargo test -p cumpleycobra` en verde (regla 7 de CLAUDE.md).
#
# Al terminar imprime el ID del contrato: va en frontend/src/lib/mainnet.ts (MAINNET.contractId)
# y en docs/mainnet.md. Para cerrar la edición experimental después del reto:
#   stellar contract invoke --id <ID> --source cyc-mainnet-arbiter --network cyc-mainnet -- pause
#
# Uso: bash scripts/mainnet_deploy.sh
set -euo pipefail

NET=cyc-mainnet
RPC=https://soroban-rpc.mainnet.stellar.gateway.fm
PASSPHRASE="Public Global Stellar Network ; September 2015"
USDC_SAC=CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75 # USDC de Circle en mainnet
ARBITER_ID=cyc-mainnet-arbiter
WASM=target/wasm32v1-none/release/cumpleycobra.wasm

if ! stellar network ls | grep -qx "$NET"; then
  stellar network add "$NET" --rpc-url "$RPC" --network-passphrase "$PASSPHRASE"
fi
ARBITER=$(stellar keys public-key "$ARBITER_ID")

echo "== Saldo del árbitro de mainnet $ARBITER"
XLM=$(curl -s "https://horizon.stellar.org/accounts/$ARBITER" | python -c \
  "import sys,json;d=json.load(sys.stdin);print(next((b['balance'] for b in d.get('balances',[]) if b['asset_type']=='native'),'0'))")
echo "   $XLM XLM"
python -c "import sys; sys.exit(0 if float('$XLM') >= 30 else 1)" || { echo "Faltan XLM: se necesitan al menos 30." >&2; exit 1; }

echo "== Tests del contrato"
cargo test -p cumpleycobra 2>&1 | grep "test result"

echo "== Compilación optimizada"
stellar contract build --optimize >/dev/null
sha256sum "$WASM"

read -r -p "Esto gasta XLM reales en mainnet. Escribe SI para desplegar: " OK
[ "$OK" = "SI" ] || { echo "Cancelado."; exit 1; }

echo "== Despliegue"
ID=$(stellar contract deploy --wasm "$WASM" --source "$ARBITER_ID" --network "$NET" --alias cumpleycobra-mainnet)
echo "   Contrato: $ID"

echo "== initialize (árbitro de mainnet + USDC de Circle)"
stellar contract invoke --id "$ID" --source "$ARBITER_ID" --network "$NET" -- \
  initialize --arbiter "$ARBITER" --token "$USDC_SAC"
stellar contract invoke --id "$ID" --source "$ARBITER_ID" --network "$NET" --send=no -- get_config

echo "== Listo. Pon este ID en frontend/src/lib/mainnet.ts y en docs/mainnet.md:"
echo "$ID"
