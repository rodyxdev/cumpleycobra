"""Acceso al contrato Soroban desde el backend (el árbitro).

Funciones síncronas: main.py las llama con run_in_threadpool para no bloquear el
event loop. La llave del árbitro nunca sale de este proceso ni se imprime.
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from stellar_sdk import Asset, Keypair, SorobanServer, TransactionBuilder, scval
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.address import Address
from stellar_sdk.exceptions import (
    BadResponseError,
    ConnectionError as StellarConnectionError,
    PrepareTransactionException,
    SorobanRpcErrorResponse,
)
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

from .config import Settings

# Números de error del contrato (contracts/cumpleycobra/src/lib.rs).
ERR_NOT_FOUND = 5
ERR_NOT_FUNDED = 6
ERR_DEADLINE_PASSED = 9

CONTRACT_ERR_RE = re.compile(r"Error\(Contract, #(\d+)\)")
BACKOFF_SECS = (1, 3)
POLL_ATTEMPTS = 30
# Todas las firmas del árbitro usan la misma cuenta y su número de secuencia: dos release en
# paralelo (dos tareas a la vez) armarían transacciones con la misma secuencia y una fallaría.
RELEASE_LOCK = threading.Lock()


class StellarUnavailable(Exception):
    """El RPC no respondió tras los reintentos."""


class ContractError(Exception):
    def __init__(self, code: int, detail: str = ""):
        super().__init__(f"Error(Contract, #{code})")
        self.code = code
        self.detail = detail


@dataclass
class ReleaseOutcome:
    status: str                 # "success" | "failed"
    transaction_hash: str | None
    detail: str = ""


def _contract_code(text: str | None) -> int | None:
    m = CONTRACT_ERR_RE.search(text or "")
    return int(m.group(1)) if m else None


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, StellarConnectionError):
        return True
    if isinstance(exc, BadResponseError):
        return exc.status == 429 or exc.status >= 500
    return False


def _with_retries(fn):
    """Reintentos con backoff (1 s y 3 s) solo ante errores transitorios del RPC."""
    for i in range(len(BACKOFF_SECS) + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if _is_transient(exc) and i < len(BACKOFF_SECS):
                time.sleep(BACKOFF_SECS[i])
                continue
            if _is_transient(exc) or isinstance(exc, SorobanRpcErrorResponse):
                raise StellarUnavailable(type(exc).__name__) from exc
            raise


def _native(value):
    if isinstance(value, Address):
        return value.address
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [_native(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _native(v) for k, v in value.items()}
    return value


class StellarClient:
    def __init__(self, settings: Settings):
        self._keypair = Keypair.from_secret(settings.arbiter_secret)
        self.arbiter_address = self._keypair.public_key
        self.contract_id = settings.contract_id
        self.usdc_sac_id = settings.usdc_sac_id
        self._usdc_asset: Asset | None = None
        self.passphrase = settings.network_passphrase
        self.server = SorobanServer(settings.rpc_url)

    def __repr__(self) -> str:
        return f"StellarClient(arbiter={self.arbiter_address}, contract={self.contract_id})"

    # --- lecturas ------------------------------------------------------------
    def ledger_time(self) -> int:
        """Timestamp (Unix, s) del último ledger cerrado: el reloj del contrato."""
        return _with_retries(lambda: self.server.get_latest_ledger().close_time)

    def _build(self, function: str, params: list, contract_id: str | None = None):
        account = _with_retries(lambda: self.server.load_account(self.arbiter_address))
        return (
            TransactionBuilder(account, self.passphrase, base_fee=100_000)
            .append_invoke_contract_function_op(contract_id or self.contract_id, function, params)
            .set_timeout(60)
            .build()
        )

    def get_task(self, task_id: str) -> dict | None:
        """Lee la tarea del contrato con una simulación (no gasta ni firma). None si no existe."""
        tx = self._build("get_task", [scval.to_string(task_id)])
        sim = _with_retries(lambda: self.server.simulate_transaction(tx))
        if sim.error:
            code = _contract_code(sim.error)
            if code == ERR_NOT_FOUND:
                return None
            if code is not None:
                raise ContractError(code, sim.error)
            raise StellarUnavailable("simulación de get_task falló")
        raw = scval.to_native(sim.results[0].xdr)
        task = _native(raw)
        status = task.get("status")
        task["status"] = status[0] if isinstance(status, list) else status
        return task

    def usdc_asset(self) -> Asset:
        """Activo clásico detrás del SAC, leído del propio SAC (name() = "CÓDIGO:EMISOR")."""
        if self._usdc_asset is None:
            tx = self._build("name", [], contract_id=self.usdc_sac_id)
            sim = _with_retries(lambda: self.server.simulate_transaction(tx))
            if sim.error or not sim.results:
                raise StellarUnavailable("no se pudo leer name() del SAC de USDC")
            name = scval.to_native(sim.results[0].xdr)
            code, issuer = name.split(":")
            self._usdc_asset = Asset(code, issuer)
        return self._usdc_asset

    def has_usdc_trustline(self, address: str) -> bool:
        """True si la cuenta tiene trustline del USDC del contrato (getLedgerEntries)."""
        asset = self.usdc_asset()
        key = stellar_xdr.LedgerKey(
            stellar_xdr.LedgerEntryType.TRUSTLINE,
            trust_line=stellar_xdr.LedgerKeyTrustLine(
                account_id=Keypair.from_public_key(address).xdr_account_id(),
                asset=asset.to_trust_line_asset_xdr_object(),
            ),
        )
        resp = _with_retries(lambda: self.server.get_ledger_entries([key]))
        return bool(resp.entries)

    def transaction_succeeded(self, tx_hash: str) -> bool:
        """True solo si el RPC confirma la transacción como SUCCESS (NOT_FOUND o FAILED: False)."""
        tx = _with_retries(lambda: self.server.get_transaction(tx_hash))
        return tx.status == GetTransactionStatus.SUCCESS

    # --- release ---------------------------------------------------------------
    def release(self, task_id: str, freelancer: str, code_hash_hex: str,
                verdict_hash_hex: str, on_signed: Callable[[str], None]) -> ReleaseOutcome:
        """Arma, prepara, firma, envía y consulta hasta SUCCESS o FAILED.

        `on_signed(hash)` se llama antes de enviar para guardar el hash en state.json.
        Lanza ContractError si la simulación devuelve un error del contrato (#6, #9…).
        Un release a la vez en todo el proceso (RELEASE_LOCK): comparten la secuencia del árbitro.
        """
        with RELEASE_LOCK:
            return self._release(task_id, freelancer, code_hash_hex, verdict_hash_hex, on_signed)

    def _release(self, task_id: str, freelancer: str, code_hash_hex: str,
                 verdict_hash_hex: str, on_signed: Callable[[str], None]) -> ReleaseOutcome:
        params = [
            scval.to_string(task_id),
            scval.to_address(freelancer),
            scval.to_bytes(bytes.fromhex(code_hash_hex)),
            scval.to_bytes(bytes.fromhex(verdict_hash_hex)),
        ]

        def prepare():
            tx = self._build("release", params)
            try:
                return self.server.prepare_transaction(tx)
            except PrepareTransactionException as exc:
                err = exc.simulate_transaction_response.error
                code = _contract_code(err)
                if code is not None:
                    raise ContractError(code, err) from None
                raise StellarUnavailable("la simulación de release falló") from None

        for i in range(len(BACKOFF_SECS) + 1):
            prepared = _with_retries(prepare)
            prepared.sign(self._keypair)
            tx_hash = prepared.hash_hex()
            on_signed(tx_hash)
            sent = _with_retries(lambda: self.server.send_transaction(prepared))
            if sent.status == SendTransactionStatus.TRY_AGAIN_LATER and i < len(BACKOFF_SECS):
                time.sleep(BACKOFF_SECS[i])
                continue
            if sent.status in (SendTransactionStatus.ERROR, SendTransactionStatus.TRY_AGAIN_LATER):
                return ReleaseOutcome("failed", tx_hash, f"sendTransaction: {sent.status.value}")
            break

        result = _with_retries(lambda: self.server.poll_transaction(tx_hash, max_attempts=POLL_ATTEMPTS))
        if result.status == GetTransactionStatus.SUCCESS:
            return ReleaseOutcome("success", tx_hash)
        if result.status == GetTransactionStatus.FAILED:
            return ReleaseOutcome("failed", tx_hash, "la transacción quedó FAILED")
        return ReleaseOutcome("failed", tx_hash, "la transacción no se confirmó a tiempo")
