"""release del árbitro: reintento ante secuencia vieja (txBAD_SEQ), sin red.

Staging y producción firman con la misma cuenta del árbitro y cada base tiene su propio candado:
si los dos pagan a la vez, uno recibe txBAD_SEQ. Esa transacción nunca se aplica, así que se arma
de nuevo con la secuencia recargada.
"""

from types import SimpleNamespace

import pytest
from stellar_sdk import Account, Keypair, StrKey
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

from backend import stellar_client
from backend.stellar_client import StellarClient


def _result_xdr(code) -> str:
    return stellar_xdr.TransactionResult(
        fee_charged=stellar_xdr.Int64(100),
        result=stellar_xdr.TransactionResultResult(code=code, results=[]),
        ext=stellar_xdr.TransactionResultExt(0),
    ).to_xdr()


class FakeServer:
    def __init__(self, sends):
        self.sends = list(sends)
        self.loads = 0
        self.sent_hashes = []

    def load_account(self, address):
        self.loads += 1
        return Account(address, 1000 + self.loads)

    def prepare_transaction(self, tx):
        return tx

    def send_transaction(self, tx):
        self.sent_hashes.append(tx.hash_hex())
        status, err = self.sends.pop(0)
        return SimpleNamespace(status=status, error_result_xdr=err)

    def poll_transaction(self, tx_hash, max_attempts):
        return SimpleNamespace(status=GetTransactionStatus.SUCCESS)


def _client(server) -> StellarClient:
    c = StellarClient.__new__(StellarClient)
    c._keypair = Keypair.random()
    c.arbiter_address = c._keypair.public_key
    c.contract_id = StrKey.encode_contract(bytes(32))
    c.passphrase = "Test SDF Network ; September 2015"
    c.server = server
    return c


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(stellar_client.time, "sleep", lambda s: None)


def _release(client, signed):
    return client.release("t1", Keypair.random().public_key, "00" * 32, "11" * 32, signed.append)


def test_secuencia_vieja_se_reintenta_con_la_cuenta_recargada():
    bad = _result_xdr(stellar_xdr.TransactionResultCode.txBAD_SEQ)
    server = FakeServer([(SendTransactionStatus.ERROR, bad), (SendTransactionStatus.PENDING, None)])
    signed = []
    out = _release(_client(server), signed)
    assert out.status == "success"
    assert server.loads == 2                      # se recargó la secuencia
    assert len(set(signed)) == 2                  # transacción nueva, hash nuevo
    assert out.transaction_hash == signed[-1]     # el hash guardado al final es el que se aplicó


def test_otro_error_de_envio_no_se_reintenta():
    other = _result_xdr(stellar_xdr.TransactionResultCode.txINSUFFICIENT_BALANCE)
    server = FakeServer([(SendTransactionStatus.ERROR, other)])
    out = _release(_client(server), [])
    assert out.status == "failed" and server.loads == 1


def test_secuencia_vieja_tiene_tope():
    bad = _result_xdr(stellar_xdr.TransactionResultCode.txBAD_SEQ)
    sends = [(SendTransactionStatus.ERROR, bad)] * (stellar_client.BAD_SEQ_RETRIES + 1)
    server = FakeServer(sends)
    out = _release(_client(server), [])
    assert out.status == "failed"
    assert server.loads == stellar_client.BAD_SEQ_RETRIES + 1


def test_xdr_ilegible_no_cuenta_como_secuencia_vieja():
    assert not stellar_client._bad_sequence("no-es-xdr")
    assert not stellar_client._bad_sequence(None)
