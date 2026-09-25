"""Identidad verificable con SEP-10: la wallet firma un reto y el backend emite una sesión.

Todo es aditivo: el flujo del dinero (invitación, /accept, depósito, /evaluate, pago) no pide
identidad. La sesión solo se exige para editar el perfil y calificar.

- Reto: build_challenge_transaction de stellar_sdk, firmado por SEP10_SIGNING_SECRET (una llave
  propia, sin fondos, distinta del árbitro). Un solo uso y 5 minutos de vida.
- Verificación: los firmantes y el umbral medio de la cuenta se leen de Horizon; si la cuenta no
  existe, se exige la firma de su llave maestra (SEP-10).
- Sesión: "<dirección>.<expira>" firmado con HMAC-SHA256 (SESSION_SECRET), válido 12 horas. Va en
  Authorization: Bearer. No se guarda en el servidor.
"""

import base64
import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass

import httpx
from stellar_sdk import Keypair, StrKey, TransactionEnvelope
from stellar_sdk.sep.ed25519_public_key_signer import Ed25519PublicKeySigner
from stellar_sdk.sep.stellar_web_authentication import (
    build_challenge_transaction,
    read_challenge_transaction,
    verify_challenge_transaction_signed_by_client_master_key,
    verify_challenge_transaction_threshold,
)

CHALLENGE_TTL = 300          # 5 minutos
SESSION_TTL = 12 * 3600      # 12 horas
HORIZON_URL = os.environ.get("HORIZON_URL", "https://horizon-testnet.stellar.org")
HOME_DOMAIN = os.environ.get("SEP10_HOME_DOMAIN", "localhost:3000")
WEB_AUTH_DOMAIN = os.environ.get("SEP10_WEB_AUTH_DOMAIN", "localhost:8000")


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class ChainError(Exception):
    """Horizon no respondió: no se consume el reto."""


@dataclass
class Keys:
    signing: Keypair
    session_secret: bytes


def load_keys(arbiter_secret: str | None) -> Keys:
    """Llaves de SEP-10 y de sesión desde el entorno. Nunca se imprimen."""
    signing = os.environ.get("SEP10_SIGNING_SECRET", "").strip()
    session = os.environ.get("SESSION_SECRET", "").strip()
    if not signing or not session:
        raise AuthError(503, "AUTH_NOT_CONFIGURED", "La verificación de identidad no está configurada en el servidor")
    keypair = Keypair.from_secret(signing)
    if arbiter_secret and Keypair.from_secret(arbiter_secret).public_key == keypair.public_key:
        # La llave del árbitro firma pagos: nunca se reutiliza para retos de identidad.
        raise AuthError(503, "AUTH_NOT_CONFIGURED", "SEP10_SIGNING_SECRET no puede ser la llave del árbitro")
    return Keys(keypair, session.encode())


def _nonce(challenge_xdr: str, passphrase: str) -> str:
    """El valor aleatorio del primer manage_data identifica al reto (sin validar nada todavía)."""
    op = TransactionEnvelope.from_xdr(challenge_xdr, passphrase).transaction.operations[0]
    return base64.b64encode(op.data_value or b"").decode()


class Challenges:
    """Retos pendientes en memoria: se consumen al primer intento y caducan a los 5 minutos."""

    def __init__(self):
        self.pending: dict[str, tuple[str, float]] = {}
        self.used: set[str] = set()
        self.lock = threading.Lock()

    def issue(self, keys: Keys, address: str, passphrase: str, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        xdr = build_challenge_transaction(keys.signing.secret, address, HOME_DOMAIN, WEB_AUTH_DOMAIN,
                                          passphrase, timeout=CHALLENGE_TTL)
        with self.lock:
            self._purge(now)
            self.pending[_nonce(xdr, passphrase)] = (address, now + CHALLENGE_TTL)
        return {"transaction": xdr, "network_passphrase": passphrase, "home_domain": HOME_DOMAIN,
                "web_auth_domain": WEB_AUTH_DOMAIN, "expires_in": CHALLENGE_TTL}

    def _purge(self, now: float) -> None:
        for nonce in [n for n, (_, exp) in self.pending.items() if exp <= now - CHALLENGE_TTL]:
            del self.pending[nonce]

    def take(self, signed_xdr: str, passphrase: str, now: float | None = None) -> tuple[str, float]:
        """Devuelve (dirección, expira) del reto y lo consume. Errores 401 con código propio."""
        now = time.time() if now is None else now
        try:
            nonce = _nonce(signed_xdr, passphrase)
        except Exception as exc:  # noqa: BLE001 - XDR que ni siquiera es una transacción
            raise AuthError(401, "CHALLENGE_INVALID", "El reto firmado no es una transacción válida") from exc
        with self.lock:
            if nonce in self.used:
                raise AuthError(401, "CHALLENGE_USED", "Ese reto ya se usó; pide uno nuevo")
            entry = self.pending.pop(nonce, None)
            if entry is None:
                raise AuthError(401, "CHALLENGE_INVALID", "Ese reto no lo emitió este servidor")
            self.used.add(nonce)
        address, expires = entry
        if now > expires:
            raise AuthError(401, "CHALLENGE_EXPIRED", "El reto caducó (5 minutos); pide uno nuevo")
        return address, expires

    def restore(self, signed_xdr: str, passphrase: str, address: str, expires: float) -> None:
        """Si Horizon no respondió, el reto vuelve a quedar pendiente (no fue culpa del usuario)."""
        nonce = _nonce(signed_xdr, passphrase)
        with self.lock:
            self.used.discard(nonce)
            self.pending[nonce] = (address, expires)


def account_signers(address: str) -> tuple[list[Ed25519PublicKeySigner], int] | None:
    """Firmantes ed25519 y umbral medio de la cuenta en Horizon; None si la cuenta no existe."""
    try:
        r = httpx.get(f"{HORIZON_URL}/accounts/{address}", timeout=10)
    except httpx.HTTPError as exc:
        raise ChainError(type(exc).__name__) from exc
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise ChainError(f"Horizon {r.status_code}")
    data = r.json()
    signers = [Ed25519PublicKeySigner(s["key"], s["weight"]) for s in data["signers"]
               if s["type"] == "ed25519_public_key"]
    return signers, int(data["thresholds"]["med_threshold"])


def verify_signed_challenge(signed_xdr: str, keys: Keys, address: str, passphrase: str, signers_lookup=account_signers) -> None:
    """Valida el reto (firma del servidor, plazo, dominio) y la firma de la cuenta. AuthError si no."""
    server = keys.signing.public_key
    try:
        challenge = read_challenge_transaction(signed_xdr, server, HOME_DOMAIN, WEB_AUTH_DOMAIN, passphrase)
    except Exception as exc:  # noqa: BLE001 - InvalidSep10ChallengeError y XDR mal formado
        raise AuthError(401, "CHALLENGE_INVALID", f"El reto no es válido ({str(exc)[:120]})") from exc
    if challenge.client_account_id != address:
        raise AuthError(401, "CHALLENGE_INVALID", "El reto es de otra dirección")
    account = signers_lookup(address)
    try:
        if account is None:
            verify_challenge_transaction_signed_by_client_master_key(signed_xdr, server, HOME_DOMAIN,
                                                                    WEB_AUTH_DOMAIN, passphrase)
        else:
            signers, med = account
            verify_challenge_transaction_threshold(signed_xdr, server, HOME_DOMAIN, WEB_AUTH_DOMAIN,
                                                   passphrase, med, signers)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(401, "SIGNATURE_INVALID", "La firma no es de la cuenta que pidió el reto") from exc


# --- Sesión -----------------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_session(keys: Keys, address: str, now: float | None = None) -> dict:
    expires = int((time.time() if now is None else now) + SESSION_TTL)
    payload = f"{address}.{expires}".encode()
    mac = hmac.new(keys.session_secret, payload, hashlib.sha256).digest()
    return {"token": f"{_b64(payload)}.{_b64(mac)}", "address": address, "expires_at": expires}


def session_address(keys: Keys, token: str, now: float | None = None) -> str:
    """Dirección de una sesión válida. AuthError 401 SESSION_REQUIRED si no lo es."""
    now = time.time() if now is None else now
    try:
        raw_payload, raw_mac = token.split(".")
        payload = base64.urlsafe_b64decode(raw_payload + "=" * (-len(raw_payload) % 4))
        mac = base64.urlsafe_b64decode(raw_mac + "=" * (-len(raw_mac) % 4))
        address, expires = payload.decode().rsplit(".", 1)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(401, "SESSION_REQUIRED", "La sesión no es válida; verifica tu identidad") from exc
    good = hmac.new(keys.session_secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(good, mac) or not StrKey.is_valid_ed25519_public_key(address):
        raise AuthError(401, "SESSION_REQUIRED", "La sesión no es válida; verifica tu identidad")
    if int(expires) <= now:
        raise AuthError(401, "SESSION_REQUIRED", "La sesión caducó; verifica tu identidad de nuevo")
    return address


def bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
