"""Verificación por ejecución (fase 3 del plan de mejora), del lado de la API.

Todo esto está detrás de `VERIFIER_ENABLED` (apagado por defecto): sin la variable, las rutas
responden 404 y `POST /tasks` rechaza `verification: "execution"`.
"""

from __future__ import annotations

import os

VERIFY_MIN_SECONDS = 300   # plazo on-chain mínimo para encolar una verificación
MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_PASTE_BYTES = 64 * 1024


def enabled() -> bool:
    return os.environ.get("VERIFIER_ENABLED", "").strip().lower() in ("1", "true", "yes")


def allowed_clients() -> frozenset[str] | None:
    """`VERIFIER_ALLOWED_CLIENTS`: direcciones G… separadas por comas que pueden crear tareas por
    ejecución (para probar en producción sin abrirlo al público). Sin la variable: todas."""
    raw = os.environ.get("VERIFIER_ALLOWED_CLIENTS", "").strip()
    if not raw:
        return None
    return frozenset(a.strip() for a in raw.split(",") if a.strip())


def client_allowed(address: str) -> bool:
    allowed = allowed_clients()
    return allowed is None or address in allowed


def queue_token() -> str | None:
    return os.environ.get("VERIFIER_QUEUE_TOKEN") or None
