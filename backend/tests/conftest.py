"""Cada prueba parte de ventanas y cuotas independientes, sin usar límites del entorno local."""
import pytest
from backend.limites import rate_limiter


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch):
    for name in ("RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_DAILY", "RATE_LIMIT_DAILY_BORRADOR",
                 "RATE_LIMIT_DAILY_MOTOR", "RATE_LIMIT_WRITES_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    rate_limiter.hits.clear()
    rate_limiter.day, rate_limiter.day_count = None, {"borrador": 0, "motor": 0}
    yield
    rate_limiter.hits.clear()
    rate_limiter.day, rate_limiter.day_count = None, {"borrador": 0, "motor": 0}


# --- Postgres -----------------------------------------------------------------------------
# Con CYC_TEST_DATABASE_URL (p. ej. el contenedor de `docker compose`), las suites de abajo corren
# también contra PostgresStore: cada `StateStore(ruta)` del test se vuelve un PostgresStore sobre la
# misma base; la primera vez que aparece una ruta se vacían las tablas.
import os  # noqa: E402
from pathlib import Path  # noqa: E402

TEST_DATABASE_URL = os.environ.get("CYC_TEST_DATABASE_URL", "").strip()
PG_SUITES = {"test_evaluate_pagos", "test_propuestas", "test_identidad", "test_reputacion",
             "test_correcciones_p1", "test_correcciones_p2", "test_delivery_fx", "test_verdicts_security_flags"}


@pytest.fixture(autouse=True)
def postgres_store(request, monkeypatch):
    module = request.module
    if not TEST_DATABASE_URL or module.__name__.rsplit(".", 1)[-1] not in PG_SUITES:
        yield
        return
    from backend.storage import postgres as pgm

    stores, seen = [], set()

    class PgTestStore(pgm.PostgresStore):
        def __init__(self, path):
            super().__init__(TEST_DATABASE_URL, max_size=4)
            self.path = Path(path)
            if self.path not in seen:
                seen.add(self.path)
                with self.pool.connection() as conn:
                    conn.execute("TRUNCATE tasks, profiles, proposals, sep10_challenges")
            stores.append(self)

    # Las fábricas de fixtures viven en varios módulos (p. ej. `world` en test_reputacion): se
    # reemplaza el nombre en todos los módulos de tests cargados.
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith("backend.tests.") and hasattr(mod, "StateStore"):
            monkeypatch.setattr(mod, "StateStore", PgTestStore)
    token = pgm._session.set(None)
    yield
    pgm._session.reset(token)
    for store in stores:
        store.close()
