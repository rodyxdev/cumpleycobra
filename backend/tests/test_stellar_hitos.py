"""Pruebas de get_project y release_milestone en StellarClient, sin red.

Falsea el servidor RPC (igual que test_stellar_release.py): comprueba que se invoca
el contrato de MILESTONES_CONTRACT_ID, que se normaliza la respuesta de get_project,
y que release_milestone comparte el manejo de errores, reintentos y txBAD_SEQ.
"""

from types import SimpleNamespace

import pytest
from stellar_sdk import Account, Address, Keypair, StrKey, scval
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.exceptions import PrepareTransactionException
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

from backend import stellar_client
from backend.stellar_client import ContractError, StellarClient, StellarUnavailable

V1_CONTRACT = StrKey.encode_contract(bytes([1] * 32))
V2_CONTRACT = StrKey.encode_contract(bytes([2] * 32))


def _result_xdr(code) -> str:
    return stellar_xdr.TransactionResult(
        fee_charged=stellar_xdr.Int64(100),
        result=stellar_xdr.TransactionResultResult(code=code, results=[]),
        ext=stellar_xdr.TransactionResultExt(0),
    ).to_xdr()


def _project_xdr(task_id: str, client: str, freelancer: str | None, milestones: list[dict]) -> str:
    m_vals = []
    for m in milestones:
        m_vals.append(scval.to_struct({
            "amount": scval.to_int128(m["amount"]),
            "deadline": scval.to_uint64(m["deadline"]),
            "rules_hash": scval.to_bytes(bytes.fromhex(m["rules_hash"])),
            "status": scval.to_vec([scval.to_symbol(m["status"])]),
        }))
    fields = {
        "client": scval.to_address(client),
        "freelancer": scval.to_address(freelancer) if freelancer else scval.to_void(),
        "milestones": scval.to_vec(m_vals),
        "task_id": scval.to_string(task_id),
    }
    return scval.to_struct(fields).to_xdr()


def _invoke_info(tx) -> tuple[str, str, list]:
    op = tx.transaction.operations[0]
    fn = op.host_function.invoke_contract
    cid = Address.from_xdr_sc_address(fn.contract_address).address
    name = fn.function_name.sc_symbol.decode("utf-8")
    args = [scval.to_native(a) for a in fn.args]
    return cid, name, args


class FakeServer:
    def __init__(self, *, sim=None, sends=(), prepare_exc=None, poll_status=GetTransactionStatus.SUCCESS):
        self.sim = sim
        self.sends = list(sends)
        self.prepare_exc = prepare_exc
        self.poll_status = poll_status
        self.loads = 0
        self.last_tx = None
        self.sent_hashes = []

    def load_account(self, address):
        self.loads += 1
        return Account(address, 2000 + self.loads)

    def simulate_transaction(self, tx):
        self.last_tx = tx
        return self.sim

    def prepare_transaction(self, tx):
        self.last_tx = tx
        if self.prepare_exc is not None:
            raise self.prepare_exc
        return tx

    def send_transaction(self, tx):
        self.sent_hashes.append(tx.hash_hex())
        status, err = self.sends.pop(0)
        return SimpleNamespace(status=status, error_result_xdr=err)

    def poll_transaction(self, tx_hash, max_attempts):
        return SimpleNamespace(status=self.poll_status)


def _client(server, milestones_contract: str | None = V2_CONTRACT) -> StellarClient:
    c = StellarClient.__new__(StellarClient)
    c._keypair = Keypair.random()
    c.arbiter_address = c._keypair.public_key
    c.contract_id = V1_CONTRACT
    c.milestones_contract_id = milestones_contract
    c.passphrase = "Test SDF Network ; September 2015"
    c.server = server
    return c


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(stellar_client.time, "sleep", lambda s: None)
    monkeypatch.delenv("MILESTONES_CONTRACT_ID", raising=False)


def test_get_project_decodifica_hitos_y_usa_contrato_de_hitos():
    client_addr = Keypair.random().public_key
    fl_addr = Keypair.random().public_key
    xdr = _project_xdr("proy-1", client_addr, fl_addr, [
        {"amount": 3_000_000, "deadline": 1_000_100, "rules_hash": "aa" * 32, "status": "Released"},
        {"amount": 5_000_000, "deadline": 1_000_200, "rules_hash": "bb" * 32, "status": "Funded"},
    ])
    server = FakeServer(sim=SimpleNamespace(error=None, results=[SimpleNamespace(xdr=xdr)]))
    project = _client(server).get_project("proy-1")
    cid, name, args = _invoke_info(server.last_tx)
    assert cid == V2_CONTRACT and cid != V1_CONTRACT
    assert name == "get_project" and args == ["proy-1"]
    assert project["task_id"] == "proy-1"
    assert project["client"] == client_addr
    assert project["freelancer"] == fl_addr
    assert [m["status"] for m in project["milestones"]] == ["Released", "Funded"]
    assert project["milestones"][1]["rules_hash"] == "bb" * 32
    assert project["milestones"][1]["amount"] == 5_000_000


def test_get_project_not_found_y_errores():
    server_nf = FakeServer(sim=SimpleNamespace(error="HostError: Error(Contract, #5)", results=[]))
    assert _client(server_nf).get_project("no-existe") is None

    server_err = FakeServer(sim=SimpleNamespace(error="HostError: Error(Contract, #1)", results=[]))
    with pytest.raises(ContractError) as exc:
        _client(server_err).get_project("x")
    assert exc.value.code == 1

    with pytest.raises(StellarUnavailable):
        _client(FakeServer(), milestones_contract=None).get_project("x")


def test_release_milestone_invoca_contrato_hitos_y_reintenta_txbad_seq():
    bad = _result_xdr(stellar_xdr.TransactionResultCode.txBAD_SEQ)
    server = FakeServer(sends=[(SendTransactionStatus.ERROR, bad), (SendTransactionStatus.PENDING, None)])
    fl = Keypair.random().public_key
    signed = []
    out = _client(server).release_milestone("proy-1", 1, fl, "11" * 32, "22" * 32, signed.append)
    assert out.status == "success"
    assert server.loads == 2
    assert len(set(signed)) == 2
    assert out.transaction_hash == signed[-1]

    cid, name, args = _invoke_info(server.last_tx)
    assert cid == V2_CONTRACT
    assert name == "release_milestone"
    assert args[0] == "proy-1" and args[1] == 1
    assert args[3] == bytes.fromhex("11" * 32) and args[4] == bytes.fromhex("22" * 32)


def test_release_milestone_propaga_errores_de_contrato_y_sin_contrato():
    resp = SimpleNamespace(error="HostError: Error(Contract, #12)")
    exc_prep = PrepareTransactionException("fallo", resp)
    server = FakeServer(prepare_exc=exc_prep)
    with pytest.raises(ContractError) as exc:
        _client(server).release_milestone("proy-1", 0, Keypair.random().public_key, "aa" * 32, "bb" * 32, lambda h: None)
    assert exc.value.code == stellar_client.ERR_WRONG_FREELANCER

    with pytest.raises(StellarUnavailable):
        _client(FakeServer(), milestones_contract=None).release_milestone(
            "proy-1", 0, Keypair.random().public_key, "aa" * 32, "bb" * 32, lambda h: None
        )


def test_release_milestone_lee_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("MILESTONES_CONTRACT_ID", V2_CONTRACT)
    server = FakeServer(sends=[(SendTransactionStatus.PENDING, None)])
    out = _client(server, milestones_contract=None).release_milestone(
        "proy-env", 0, Keypair.random().public_key, "aa" * 32, "bb" * 32, lambda h: None
    )
    assert out.status == "success"
    cid, name, _ = _invoke_info(server.last_tx)
    assert cid == V2_CONTRACT and name == "release_milestone"
