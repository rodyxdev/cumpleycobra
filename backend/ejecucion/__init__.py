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


def queue_token() -> str | None:
    return os.environ.get("VERIFIER_QUEUE_TOKEN") or None
