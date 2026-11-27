"""Firma la entrada de autorización Soroban (`SorobanAuthorizationEntry`) de una identidad local.

Útil cuando una función del contrato exige doble firma (por ejemplo cliente + árbitro) y la
segunda dirección se lee del almacenamiento del contrato en lugar de pasarse por CLI.
Nunca imprime llaves privadas: solo recibe el XDR base64 y devuelve el XDR firmado.
"""

from __future__ import annotations

import subprocess
import sys

from stellar_sdk import Address, Keypair, Network, SorobanServer, TransactionEnvelope, auth
from stellar_sdk import xdr as sxdr

RPC_URL = "https://soroban-testnet.stellar.org"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Uso: sign_soroban_auth.py <identidad-stellar> <tx_xdr>")
    identity, tx_xdr = sys.argv[1], sys.argv[2].strip()
    secret = subprocess.check_output(["stellar", "keys", "secret", identity], text=True).strip()
    kp = Keypair.from_secret(secret)
    passphrase = Network.TESTNET_NETWORK_PASSPHRASE
    env = TransactionEnvelope.from_xdr(tx_xdr, passphrase)
    latest = SorobanServer(RPC_URL).get_latest_ledger().sequence
    valid_until = latest + 100

    signed_any = False
    for op in env.transaction.operations:
        if not hasattr(op, "auth") or not op.auth:
            continue
        new_auth = []
        for entry in op.auth:
            creds = entry.credentials
            if (
                creds.type == sxdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS
                and Address.from_xdr_sc_address(creds.address.address).address == kp.public_key
            ):
                entry = auth.authorize_entry(entry, kp, valid_until, passphrase)
                signed_any = True
            new_auth.append(entry)
        op.auth = new_auth

    if not signed_any:
        raise SystemExit(f"No se encontró entrada de autorización Soroban para {identity} ({kp.public_key})")
    print(env.to_xdr())


if __name__ == "__main__":
    main()
