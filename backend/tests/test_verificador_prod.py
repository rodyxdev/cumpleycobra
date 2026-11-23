"""Verificador antes de producción: costo de la suite, suites trabadas y reintento del cliente.

- La suite cuesta modelo y VM antes del depósito: cupo de suites activas, ventana por IP y cuota diaria.
- Una suite cuyo trabajo venció sin pasar por /fail (VM Spot detenida) se reencola o se rechaza.
- El cliente puede pedir otro intento de una suite rechazada sin crear otra tarea (máximo 2).
- Cada verificación por ejecución consume la cuota diaria `verificacion`, después de las guardias.
"""

import pytest

from backend import main
from backend.ejecucion import cola
from backend.ejecucion import rutas as exec_rutas
from backend.limites import rate_limiter

from .test_verificador import (  # noqa: F401 - fixtures
    CLIENT, DEMO_SPEC, AMOUNT, INTERFACE, accepted_task, create_task, drive_suite, fake_llm, submit,
    worker_headers, world,
)


def body():
    return {"client_address": CLIENT, **DEMO_SPEC, "amount": AMOUNT, "deadline_minutes": 60,
            "verification": "execution", "interface": INTERFACE}


def age_suite(task_id, secs=exec_rutas.SUITE_GRACE_SECS + 1):
    task = main.app.state.store.tasks[task_id]
    task["suite"]["started_at"] -= secs


# --- costo de la suite ---------------------------------------------------------------------

def test_cupo_de_suites_activas(world, monkeypatch):
    monkeypatch.setenv("MAX_PENDING_SUITES", "2")
    create_task(world)
    create_task(world)
    r = world.post("/tasks", json=body())
    assert r.status_code == 503 and r.json()["error"] == "VERIFIER_BUSY"
    assert len(main.app.state.store.tasks) == 2  # no se creó la tarea
    # Una suite termina: hay lugar otra vez.
    drive_suite(world, next(iter(main.app.state.store.tasks)))
    assert world.post("/tasks", json=body()).status_code == 200


def test_ventana_por_ip_para_suites(world, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SUITES_PER_MINUTE", "1")
    create_task(world)
    r = world.post("/tasks", json=body())
    assert r.status_code == 429 and r.json()["error"] == "RATE_LIMITED"
    # Una tarea estática no pasa por ese límite.
    static = {k: v for k, v in body().items() if k not in ("verification", "interface")}
    assert world.post("/tasks", json=static).status_code == 200


def test_cuota_diaria_de_suites_y_rechazo_previo_no_gasta(world, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY_SUITE", "1")
    bad = {**body(), "interface": None}
    assert world.post("/tasks", json=bad).status_code == 400   # inválida: no consume cuota
    create_task(world)
    r = world.post("/tasks", json=body())
    assert r.status_code == 429 and "tareas con verificación por ejecución" in r.json()["message"]


def test_modo_publico_fija_los_limites_del_verificador(monkeypatch):
    from backend import config
    for name in ("RATE_LIMIT_DAILY_SUITE", "RATE_LIMIT_DAILY_VERIFICACION", "RATE_LIMIT_SUITES_PER_MINUTE",
                 "MAX_PENDING_SUITES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_MODE", "demo")
    import os
    config.apply_mode_defaults()
    assert os.environ["RATE_LIMIT_DAILY_SUITE"] == "50"
    assert os.environ["RATE_LIMIT_DAILY_VERIFICACION"] == "200"
    assert os.environ["RATE_LIMIT_SUITES_PER_MINUTE"] == "2"
    assert os.environ["MAX_PENDING_SUITES"] == "10"


def test_cuota_diaria_de_verificaciones(world, monkeypatch):
    created, ft = accepted_task(world)
    tid = created["task_id"]
    monkeypatch.setenv("RATE_LIMIT_DAILY_VERIFICACION", "1")
    assert submit(world, tid, "otro", {"kind": "code", "code": "x = 1"}).status_code == 403  # no gasta
    assert submit(world, tid, ft, {"kind": "code", "code": "x = 1"}).status_code == 202
    assert rate_limiter.day_count["verificacion"] == 1


# --- suites trabadas ---------------------------------------------------------------------

def expire_running(job_id):
    q: cola.MemoryQueue = main.app.state.queue
    q.jobs[job_id]["lease_until"] = 0


def test_suite_con_trabajo_vencido_se_reencola(world):
    created = create_task(world)
    tid = created["task_id"]
    # Tres reclamos sin respuesta: el trabajo queda failed por plazo, sin pasar por /fail.
    for _ in range(cola.MAX_ATTEMPTS):
        job = world.post("/verifier/claim", headers=worker_headers()).json()
        expire_running(job["id"])
    assert main.app.state.queue.get(job["id"])["status"] == "failed"
    age_suite(tid)
    plan = world.get(f"/tasks/{tid}/suite").json()
    assert plan["status"] == "pendiente"
    task = main.app.state.store.tasks[tid]
    assert task["suite_job"] != job["id"]
    assert main.app.state.queue.get(task["suite_job"])["status"] == "queued"


def test_suite_sin_intentos_se_rechaza_y_se_puede_reintentar(world):
    created = create_task(world)
    tid = created["task_id"]
    for _ in range(exec_rutas.SUITE_JOB_ATTEMPTS):
        for _ in range(cola.MAX_ATTEMPTS):
            job = world.post("/verifier/claim", headers=worker_headers()).json()
            expire_running(job["id"])
        age_suite(tid)
        world.get(f"/tasks/{tid}")  # GET /tasks también recupera
    plan = world.get(f"/tasks/{tid}/suite").json()
    assert plan["status"] == "rechazada"
    assert "otro intento" in plan["error"] and plan["retries_left"] == 2

    r = world.post(f"/tasks/{tid}/suite/reintentar", headers={"X-Client-Token": created["client_token"]})
    assert r.status_code == 202 and r.json()["status"] == "pendiente" and r.json()["retries_left"] == 1
    drive_suite(world, tid)
    assert main.app.state.store.tasks[tid]["suite"]["status"] == "lista"


def test_suite_recien_encolada_no_se_toca(world):
    created = create_task(world)
    tid = created["task_id"]
    job = world.post("/verifier/claim", headers=worker_headers()).json()
    expire_running(job["id"])
    main.app.state.queue.jobs[job["id"]]["attempts"] = cola.MAX_ATTEMPTS
    world.get(f"/tasks/{tid}/suite")  # dentro del periodo de gracia
    assert main.app.state.store.tasks[tid]["suite_job"] == job["id"]


# --- reintento pedido por el cliente -------------------------------------------------------

def rejected_task(client):
    created = create_task(client)
    drive_suite(client, created["task_id"], stub_passes=True)  # nunca valida: rechazada
    assert main.app.state.store.tasks[created["task_id"]]["suite"]["status"] == "rechazada"
    return created


def test_reintento_exige_token_y_suite_rechazada(world):
    created = create_task(world)
    tid = created["task_id"]
    r = world.post(f"/tasks/{tid}/suite/reintentar", headers={"X-Client-Token": "otro"})
    assert r.status_code == 403
    r = world.post(f"/tasks/{tid}/suite/reintentar", headers={"X-Client-Token": created["client_token"]})
    assert r.status_code == 409 and r.json()["error"] == "SUITE_NOT_REJECTED"


def test_reintentos_tienen_tope_y_no_cambian_el_rules_hash(world):
    created = rejected_task(world)
    tid = created["task_id"]
    headers = {"X-Client-Token": created["client_token"]}
    for left in (1, 0):
        r = world.post(f"/tasks/{tid}/suite/reintentar", headers=headers)
        assert r.status_code == 202 and r.json()["retries_left"] == left
        drive_suite(world, tid, stub_passes=True)
    r = world.post(f"/tasks/{tid}/suite/reintentar", headers=headers)
    assert r.status_code == 429 and r.json()["error"] == "TOO_MANY_SUITE_RETRIES"
    assert main.app.state.store.tasks[tid]["rules_hash"] == created["rules_hash"]


def test_falla_de_un_trabajo_viejo_no_toca_la_suite_nueva(world):
    created = rejected_task(world)
    tid = created["task_id"]
    task = main.app.state.store.tasks[tid]
    # Un trabajo de la suite anterior sigue vivo (p. ej. reclamado antes del reintento).
    old = main.app.state.queue.enqueue("suite", tid, {"spec": {}})
    world.post(f"/tasks/{tid}/suite/reintentar", headers={"X-Client-Token": created["client_token"]})
    new_job = task["suite_job"]
    claimed = world.post("/verifier/claim", headers=worker_headers()).json()
    assert claimed["id"] == old["id"]
    world.post(f"/verifier/jobs/{old['id']}/fail", headers=worker_headers(),
               json={"lease_id": claimed["lease_id"], "message": "vieja"})
    assert task["suite_job"] == new_job and task["suite"]["status"] == "pendiente"


def test_reintento_usa_la_cuota_de_suites(world, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DAILY_SUITE", "1")
    created = rejected_task(world)  # crear la tarea gastó la única suite del día
    r = world.post(f"/tasks/{created['task_id']}/suite/reintentar",
                   headers={"X-Client-Token": created["client_token"]})
    assert r.status_code == 429
    assert main.app.state.store.tasks[created["task_id"]]["suite"]["status"] == "rechazada"


@pytest.mark.parametrize("path", ["/tasks/x/suite/reintentar"])
def test_reintento_es_404_sin_flag(world, monkeypatch, path):
    monkeypatch.delenv("VERIFIER_ENABLED")
    assert world.post(path).status_code == 404
