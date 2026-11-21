"""Dónde vive el estado del backend: `state.json` (por defecto) o Postgres.

STATE_BACKEND=json      → StateStore (backend/state.py): un solo proceso, archivo atómico.
STATE_BACKEND=postgres  → PostgresStore: varias instancias, candados en la base (DATABASE_URL).

Las dos exponen la misma interfaz (tasks, profiles, proposals, lock, save). El contrato
sigue siendo la fuente de verdad del dinero; aquí viven tareas, tokens, envíos y veredictos.
"""

from __future__ import annotations

import os
from pathlib import Path


class StorageConfigError(RuntimeError):
    pass


def backend_name() -> str:
    name = (os.environ.get("STATE_BACKEND") or "json").strip().lower()
    if name not in {"json", "postgres"}:
        raise StorageConfigError("STATE_BACKEND debe ser 'json' o 'postgres'")
    return name


def make_store(state_file: Path):
    if backend_name() == "postgres":
        from backend.storage.postgres import PostgresStore

        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise StorageConfigError("STATE_BACKEND=postgres requiere DATABASE_URL")
        return PostgresStore(url)
    from backend.state import StateStore

    return StateStore(state_file)
