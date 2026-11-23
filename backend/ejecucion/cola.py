"""Cola de trabajos del verificador (fase 3).

Dos implementaciones con la misma interfaz:
- `MemoryQueue`: para `STATE_BACKEND=json` (laptop, un solo proceso).
- `PgQueue`: tabla `verifier_jobs`; `claim` usa `FOR UPDATE SKIP LOCKED`, así que varios
  trabajadores (o varias VMs) nunca toman el mismo trabajo.

Un trabajo reclamado lleva un `lease_id` aleatorio y un plazo (`lease_until`). El trabajador debe
presentar ese `lease_id` para informar avance o entregar el resultado; si el plazo vence sin
noticias, el trabajo vuelve a la cola (hasta `MAX_ATTEMPTS`; después queda `failed`).

Además guarda los ZIP de las entregas (`put_source` / `get_source`): en memoria o en
`verifier_sources`. Nunca en el documento de la tarea.
"""

from __future__ import annotations

import copy
import json
import secrets
import threading
import time
from typing import Protocol

LEASE_SECS = 180          # el trabajador renueva el plazo con cada avance
MAX_ATTEMPTS = 3
MAX_PROGRESS = 50
EXPIRED = {"error": "El verificador no terminó el trabajo a tiempo"}


class LeaseError(Exception):
    """El trabajo no existe, ya terminó o el lease_id no es el vigente."""


def _job(kind: str, task_id: str, payload: dict) -> dict:
    now = time.time()
    return {"id": secrets.token_urlsafe(12), "kind": kind, "task_id": task_id, "status": "queued",
            "payload": payload, "progress": [], "result": None, "attempts": 0,
            "lease_id": None, "lease_until": None, "created_at": now, "updated_at": now}


def _event(event: dict) -> dict:
    return {"stage": str(event.get("stage", ""))[:40], "detail": str(event.get("detail", ""))[:300],
            "at": round(time.time(), 3)}


def _lease_ok(job: dict | None, lease_id: str | None) -> bool:
    return bool(job and job["status"] == "running" and lease_id
                and secrets.compare_digest(job["lease_id"] or "", lease_id))


class Queue(Protocol):
    def enqueue(self, kind: str, task_id: str, payload: dict) -> dict: ...
    def claim(self, kinds: tuple[str, ...] = ("suite", "verify")) -> dict | None: ...
    def get(self, job_id: str) -> dict | None: ...
    def progress(self, job_id: str, lease_id: str, event: dict) -> dict: ...
    def finish(self, job_id: str, lease_id: str, status: str, result: dict) -> dict: ...
    def for_task(self, task_id: str) -> list[dict]: ...
    def put_source(self, task_id: str, data: bytes) -> str: ...
    def get_source(self, source_id: str) -> bytes | None: ...
    def stats(self) -> dict: ...


def _stats(rows) -> dict:
    """Trabajos activos por estado y tipo, y el más viejo en cola (para límites y monitoreo)."""
    out = {"queued": {"suite": 0, "verify": 0}, "running": {"suite": 0, "verify": 0}, "oldest_queued_at": None}
    for kind, status, created_at in rows:
        out[status][kind] = out[status].get(kind, 0) + 1
        if status == "queued" and (out["oldest_queued_at"] is None or created_at < out["oldest_queued_at"]):
            out["oldest_queued_at"] = created_at
    return out


class MemoryQueue:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.sources: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        for job in self.jobs.values():
            if job["status"] == "running" and job["lease_until"] is not None and job["lease_until"] < now:
                failed = job["attempts"] >= MAX_ATTEMPTS
                job.update(status="failed" if failed else "queued", lease_id=None, lease_until=None, updated_at=now)
                if failed:
                    job["result"] = dict(EXPIRED)

    def enqueue(self, kind, task_id, payload):
        job = _job(kind, task_id, payload)
        with self._lock:
            self.jobs[job["id"]] = job
            return copy.deepcopy(job)

    def claim(self, kinds=("suite", "verify")):
        now = time.time()
        with self._lock:
            self._expire(now)
            queued = sorted((j for j in self.jobs.values() if j["status"] == "queued" and j["kind"] in kinds),
                            key=lambda j: j["created_at"])
            if not queued:
                return None
            job = queued[0]
            job.update(status="running", attempts=job["attempts"] + 1, lease_id=secrets.token_urlsafe(24),
                       lease_until=now + LEASE_SECS, updated_at=now)
            return copy.deepcopy(job)

    def get(self, job_id):
        with self._lock:
            self._expire(time.time())
            job = self.jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def progress(self, job_id, lease_id, event):
        with self._lock:
            job = self.jobs.get(job_id)
            if not _lease_ok(job, lease_id):
                raise LeaseError(job_id)
            if len(job["progress"]) < MAX_PROGRESS:
                job["progress"].append(_event(event))
            now = time.time()
            job.update(lease_until=now + LEASE_SECS, updated_at=now)
            return copy.deepcopy(job)

    def finish(self, job_id, lease_id, status, result):
        with self._lock:
            job = self.jobs.get(job_id)
            if not _lease_ok(job, lease_id):
                raise LeaseError(job_id)
            job.update(status=status, result=result, lease_id=None, lease_until=None, updated_at=time.time())
            return copy.deepcopy(job)

    def for_task(self, task_id):
        with self._lock:
            self._expire(time.time())  # un plazo vencido no debe parecer trabajo activo
            jobs = sorted((j for j in self.jobs.values() if j["task_id"] == task_id), key=lambda j: j["created_at"])
            return copy.deepcopy(jobs)

    def put_source(self, task_id, data):
        source_id = secrets.token_urlsafe(12)
        with self._lock:
            self.sources[source_id] = bytes(data)
        return source_id

    def get_source(self, source_id):
        with self._lock:
            return self.sources.get(source_id)

    def stats(self):
        with self._lock:
            self._expire(time.time())
            return _stats([(j["kind"], j["status"], j["created_at"]) for j in self.jobs.values()
                           if j["status"] in ("queued", "running")])


_KEYS = ("id", "kind", "task_id", "status", "payload", "progress", "result", "attempts",
         "lease_id", "lease_until", "created_at", "updated_at")
_COLUMNS = ", ".join(_KEYS)


def _row(row) -> dict | None:
    if row is None:
        return None
    job = dict(zip(_KEYS, row, strict=True))
    for key in ("payload", "progress", "result"):
        if isinstance(job[key], str):
            job[key] = json.loads(job[key])
    return job


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PgQueue:
    def __init__(self, pool):
        self.pool = pool

    def _expire(self, conn, now: float) -> None:
        conn.execute(
            "UPDATE verifier_jobs SET status = CASE WHEN attempts < %s THEN 'queued' ELSE 'failed' END, "
            "result = CASE WHEN attempts < %s THEN result ELSE %s::json END, "
            "lease_id = NULL, lease_until = NULL, updated_at = %s "
            "WHERE status = 'running' AND lease_until < %s",
            (MAX_ATTEMPTS, MAX_ATTEMPTS, _dumps(EXPIRED), now, now))

    def enqueue(self, kind, task_id, payload):
        job = _job(kind, task_id, payload)
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO verifier_jobs (id, kind, task_id, status, payload, progress, attempts, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'queued', %s, '[]', 0, %s, %s)",
                (job["id"], kind, task_id, _dumps(payload), job["created_at"], job["updated_at"]))
        return job

    def claim(self, kinds=("suite", "verify")):
        now = time.time()
        with self.pool.connection() as conn, conn.transaction():
            self._expire(conn, now)
            row = conn.execute(
                "SELECT id FROM verifier_jobs WHERE status = 'queued' AND kind = ANY(%s) "
                "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED", (list(kinds),)).fetchone()
            if row is None:
                return None
            return _row(conn.execute(
                f"UPDATE verifier_jobs SET status = 'running', attempts = attempts + 1, lease_id = %s, "
                f"lease_until = %s, updated_at = %s WHERE id = %s RETURNING {_COLUMNS}",
                (secrets.token_urlsafe(24), now + LEASE_SECS, now, row[0])).fetchone())

    def get(self, job_id):
        with self.pool.connection() as conn:
            self._expire(conn, time.time())
            return _row(conn.execute(f"SELECT {_COLUMNS} FROM verifier_jobs WHERE id = %s", (job_id,)).fetchone())

    def _leased(self, conn, job_id, lease_id) -> dict:
        job = _row(conn.execute(f"SELECT {_COLUMNS} FROM verifier_jobs WHERE id = %s FOR UPDATE", (job_id,)).fetchone())
        if not _lease_ok(job, lease_id):
            raise LeaseError(job_id)
        return job

    def progress(self, job_id, lease_id, event):
        now = time.time()
        with self.pool.connection() as conn, conn.transaction():
            job = self._leased(conn, job_id, lease_id)
            events = job["progress"] + [_event(event)] if len(job["progress"]) < MAX_PROGRESS else job["progress"]
            return _row(conn.execute(
                f"UPDATE verifier_jobs SET progress = %s, lease_until = %s, updated_at = %s "
                f"WHERE id = %s RETURNING {_COLUMNS}", (_dumps(events), now + LEASE_SECS, now, job_id)).fetchone())

    def finish(self, job_id, lease_id, status, result):
        with self.pool.connection() as conn, conn.transaction():
            self._leased(conn, job_id, lease_id)
            return _row(conn.execute(
                f"UPDATE verifier_jobs SET status = %s, result = %s, lease_id = NULL, lease_until = NULL, "
                f"updated_at = %s WHERE id = %s RETURNING {_COLUMNS}",
                (status, _dumps(result), time.time(), job_id)).fetchone())

    def for_task(self, task_id):
        with self.pool.connection() as conn, conn.transaction():
            self._expire(conn, time.time())  # un plazo vencido no debe parecer trabajo activo
            rows = conn.execute(f"SELECT {_COLUMNS} FROM verifier_jobs WHERE task_id = %s ORDER BY created_at",
                                (task_id,)).fetchall()
        return [_row(r) for r in rows]

    def put_source(self, task_id, data):
        source_id = secrets.token_urlsafe(12)
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO verifier_sources (id, task_id, data) VALUES (%s, %s, %s)",
                         (source_id, task_id, bytes(data)))
        return source_id

    def get_source(self, source_id):
        with self.pool.connection() as conn:
            row = conn.execute("SELECT data FROM verifier_sources WHERE id = %s", (source_id,)).fetchone()
        return bytes(row[0]) if row else None

    def stats(self):
        with self.pool.connection() as conn, conn.transaction():
            self._expire(conn, time.time())
            rows = conn.execute("SELECT kind, status, created_at FROM verifier_jobs "
                                "WHERE status IN ('queued', 'running')").fetchall()
        return _stats(rows)


def make_queue(store) -> Queue:
    """Postgres si el estado vive en Postgres; en memoria con `state.json`."""
    pool = getattr(store, "pool", None)
    return PgQueue(pool) if pool is not None else MemoryQueue()
