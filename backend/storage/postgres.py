"""Estado del backend en Postgres, con la misma interfaz que StateStore (backend/state.py).

Diseño:
- Una fila por entidad (`tasks`, `profiles`, `proposals`) con el mismo documento que state.json,
  en una columna `json` que conserva el orden de las claves. El código del backend no cambia de
  forma: lee un documento, lo modifica y llama a `save()`.
- Mapa de identidad por petición (ContextVar): dentro de una petición, la misma clave devuelve el
  mismo dict; `save()` escribe solo los documentos que cambiaron, en una transacción.
- `lock(clave)`: asyncio.Lock local (orden dentro de la instancia) + `pg_advisory_lock` en una
  conexión propia (exclusión entre instancias). Al entrar se descartan las lecturas sin cambios de
  la petición, para que lo que se lea dentro del candado venga fresco de la base.
- Lecturas y escrituras son síncronas (psycopg 3 + pool): tardan milisegundos en la misma región,
  igual que la escritura de state.json, que también bloqueaba el event loop.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import threading
from collections.abc import Iterator, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path

from psycopg_pool import ConnectionPool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
TABLES = ("tasks", "profiles", "proposals")
LOCK_SQL = "SELECT pg_advisory_lock(hashtextextended(%s, 0))"
UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"
MIGRATIONS_LOCK = "cyc:migraciones"

_session: contextvars.ContextVar["_Session | None"] = contextvars.ContextVar("cyc_store_session", default=None)


def dumps(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


class _Session:
    """Documentos leídos o creados en esta petición: (tabla, clave) → [doc, texto guardado | None]."""

    def __init__(self, implicit: bool = False):
        self.docs: dict[tuple[str, str], list] = {}
        # Fuera de una petición (scripts, consola, tests) no hay quien abra y cierre la sesión:
        # cada lectura de un documento sin cambios se recarga de la base.
        self.implicit = implicit

    def clean_keys(self) -> list[tuple[str, str]]:
        return [key for key, (doc, saved) in self.docs.items() if saved is not None and dumps(doc) == saved]


def _replace_in_place(entry: list, fresh) -> None:
    """Pone el contenido fresco en el MISMO dict para no romper referencias que ya tenga el código."""
    if dumps(fresh) == entry[1]:
        return
    if isinstance(entry[0], dict) and isinstance(fresh, dict):
        entry[0].clear()
        entry[0].update(fresh)
    else:
        entry[0] = fresh
    entry[1] = dumps(entry[0])


def migrate(pool: ConnectionPool) -> list[str]:
    """Aplica en orden las migraciones pendientes (`migrations/NNN_*.sql`). Devuelve las aplicadas."""
    applied: list[str] = []
    with pool.connection() as conn:
        conn.execute(LOCK_SQL, (MIGRATIONS_LOCK,))
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                         "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                applied.append(path.stem)
        finally:
            conn.execute(UNLOCK_SQL, (MIGRATIONS_LOCK,))
    return applied


class DocMap(MutableMapping):
    """Vista tipo dict de una tabla de documentos, en el orden de creación (`seq`)."""

    def __init__(self, store: "PostgresStore", table: str):
        assert table in TABLES
        self._store = store
        self._table = table

    def _entry(self, key: str) -> list | None:
        session = self._store.session()
        entry = session.docs.get((self._table, key))
        if entry is not None:
            if session.implicit and dumps(entry[0]) == entry[1]:
                self._store.refresh()
                entry = session.docs.get((self._table, key))
            if entry is not None:
                return entry
        with self._store.pool.connection() as conn:
            row = conn.execute(f"SELECT doc::text FROM {self._table} WHERE id = %s", (key,)).fetchone()
        if row is None:
            return None
        doc = json.loads(row[0])
        entry = [doc, dumps(doc)]
        session.docs[(self._table, key)] = entry
        return entry

    def __getitem__(self, key: str):
        entry = self._entry(key)
        if entry is None:
            raise KeyError(key)
        return entry[0]

    def get(self, key: str, default=None):
        entry = self._entry(key)
        return default if entry is None else entry[0]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._entry(key) is not None

    def __setitem__(self, key: str, value) -> None:
        self._store.session().docs[(self._table, key)] = [value, None]

    def __delitem__(self, key: str) -> None:
        with self._store.pool.connection() as conn:
            deleted = conn.execute(f"DELETE FROM {self._table} WHERE id = %s", (key,)).rowcount
        found = self._store.session().docs.pop((self._table, key), None)
        if not deleted and found is None:
            raise KeyError(key)

    def _all(self) -> list[tuple[str, object]]:
        session = self._store.session()
        with self._store.pool.connection() as conn:
            rows = conn.execute(f"SELECT id, doc::text FROM {self._table} ORDER BY seq").fetchall()
        out, seen = [], set()
        for key, text in rows:
            entry = session.docs.get((self._table, key))
            if entry is None:
                doc = json.loads(text)
                entry = [doc, dumps(doc)]
                session.docs[(self._table, key)] = entry
            elif session.implicit and dumps(entry[0]) == entry[1]:
                _replace_in_place(entry, json.loads(text))
            out.append((key, entry[0]))
            seen.add(key)
        # Creados en esta petición y todavía sin guardar: al final, como en un dict.
        out += [(key, entry[0]) for (table, key), entry in session.docs.items()
                if table == self._table and key not in seen]
        return out

    def __iter__(self) -> Iterator[str]:
        return iter([key for key, _ in self._all()])

    def __len__(self) -> int:
        return len(self._all())

    def values(self):
        return [doc for _, doc in self._all()]

    def items(self):
        return self._all()


class _AdvisoryLock:
    """Candado síncrono entre instancias (para hilos, p. ej. el release del árbitro)."""

    def __init__(self, pool: ConnectionPool, key: str):
        self._pool = pool
        self._key = key
        self._local = threading.local()

    def __enter__(self):
        conn = self._pool.getconn()
        try:
            conn.execute(LOCK_SQL, (self._key,))
        except BaseException:
            self._pool.putconn(conn)
            raise
        self._local.conn = conn
        return self

    def __exit__(self, *exc):
        conn = self._local.conn
        try:
            conn.execute(UNLOCK_SQL, (self._key,))
        except Exception:  # noqa: BLE001 - al cerrar la sesión, Postgres suelta el candado
            conn.close()
        finally:
            self._pool.putconn(conn)
        return False


class PostgresStore:
    def __init__(self, url: str, *, max_size: int = 10):
        self.pool = ConnectionPool(url, min_size=1, max_size=max_size, kwargs={"autocommit": True}, open=True)
        self.pool.wait(timeout=30)
        self.applied_migrations = migrate(self.pool)
        self.tasks = DocMap(self, "tasks")
        self.profiles = DocMap(self, "profiles")
        self.proposals = DocMap(self, "proposals")
        self._local_locks: dict[str, asyncio.Lock] = {}

    # --- Sesión por petición ---------------------------------------------------
    def session(self) -> _Session:
        session = _session.get()
        if session is None:
            session = _Session(implicit=True)
            _session.set(session)
        return session

    def begin(self) -> contextvars.Token:
        """Abre una sesión limpia (la llama el middleware al empezar cada petición)."""
        return _session.set(_Session())

    def end(self, token: contextvars.Token) -> None:
        _session.reset(token)

    # --- Escritura -------------------------------------------------------------
    def save(self) -> None:
        """Escribe, en una sola transacción, los documentos de la petición que cambiaron."""
        session = self.session()
        dirty = []
        for (table, key), entry in session.docs.items():
            text = dumps(entry[0])
            if text != entry[1]:
                dirty.append((table, key, text, entry))
        if not dirty:
            return
        with self.pool.connection() as conn, conn.transaction():
            for table, key, text, _ in dirty:
                conn.execute(
                    f"INSERT INTO {table} (id, doc) VALUES (%s, %s::json) "
                    "ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()",
                    (key, text),
                )
        for _, _, text, entry in dirty:
            entry[1] = text

    def refresh(self) -> None:
        """Recarga EN SU LUGAR los documentos sin cambios de la petición.

        Se llama al entrar a un candado: otra instancia pudo escribir mientras esperábamos. Se
        actualiza el mismo dict (no se reemplaza) para que las referencias que ya tenga el código
        vean los datos frescos y sigan registradas para `save()`.
        """
        session = self.session()
        by_table: dict[str, list[str]] = {}
        for table, key in session.clean_keys():
            by_table.setdefault(table, []).append(key)
        if not by_table:
            return
        with self.pool.connection() as conn:
            for table, keys in by_table.items():
                fresh = dict(conn.execute(f"SELECT id, doc::text FROM {table} WHERE id = ANY(%s)", (keys,)).fetchall())
                for key in keys:
                    entry = session.docs[(table, key)]
                    text = fresh.get(key)
                    if text is None:  # la borró otra instancia
                        del session.docs[(table, key)]
                        continue
                    _replace_in_place(entry, json.loads(text))

    # --- Candados --------------------------------------------------------------
    @asynccontextmanager
    async def lock(self, key: str):
        self.session()  # crearla aquí: los hilos de to_thread comparten el objeto, no la variable
        local = self._local_locks.setdefault(key, asyncio.Lock())
        async with local:
            conn = await asyncio.to_thread(self.pool.getconn)
            try:
                await asyncio.to_thread(conn.execute, LOCK_SQL, (key,))
            except BaseException:
                self.pool.putconn(conn)
                raise
            try:
                await asyncio.to_thread(self.refresh)
                yield
            finally:
                try:
                    await asyncio.to_thread(conn.execute, UNLOCK_SQL, (key,))
                except Exception:  # noqa: BLE001 - al cerrar la sesión, Postgres suelta el candado
                    conn.close()
                finally:
                    self.pool.putconn(conn)

    def sync_lock(self, key: str) -> _AdvisoryLock:
        return _AdvisoryLock(self.pool, key)

    def close(self) -> None:
        self.pool.close()
