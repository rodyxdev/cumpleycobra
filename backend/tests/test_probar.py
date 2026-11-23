"""GET /probar: reparte tareas de prueba ya depositadas (botón «Pruébalo» de la demo)."""

from stellar_sdk import Keypair

from backend import main

from .test_verificador import (  # noqa: F401 - fixtures
    CLIENT, FREELANCER, create_task, drive_suite, fake_llm, world,
)

OTHER = Keypair.random().public_key


def ready_tasks(client, n):
    ids = []
    for _ in range(n):
        created = create_task(client)
        drive_suite(client, created["task_id"])
        ids.append(created["task_id"])
    return ids


def test_sin_tareas_configuradas(world, monkeypatch):
    monkeypatch.delenv("DEMO_TRIAL_TASKS", raising=False)
    r = world.get(f"/probar?address={FREELANCER}")
    assert r.status_code == 404 and r.json()["error"] == "NO_TRIAL_TASKS"


def test_exige_una_direccion_valida(world, monkeypatch):
    monkeypatch.setenv("DEMO_TRIAL_TASKS", "x")
    assert world.get("/probar").status_code == 400
    assert world.get("/probar?address=hola").status_code == 400


def test_reparte_una_libre_y_la_misma_a_quien_ya_la_tomo(world, monkeypatch):
    ids = ready_tasks(world, 2)
    monkeypatch.setenv("DEMO_TRIAL_TASKS", ",".join(ids) + ",no-existe")
    r = world.get(f"/probar?address={FREELANCER}").json()
    assert r["task_id"] in ids and r["available"] == 2 and not r["yours"]
    token = main.app.state.store.tasks[r["task_id"]]["invite_token"]
    assert r["invite_path"] == f"/tarea/{r['task_id']}?invitacion={token}"
    # La acepta: desde ahí /probar le devuelve la suya, y a otra wallet le da la que queda.
    world.post(f"/tasks/{r['task_id']}/accept", json={"freelancer_address": FREELANCER, "invite_token": token})
    again = world.get(f"/probar?address={FREELANCER}").json()
    assert again["task_id"] == r["task_id"] and again["yours"] and again["available"] == 1
    other = world.get(f"/probar?address={OTHER}").json()
    assert other["task_id"] != r["task_id"] and other["task_id"] in ids


def test_no_reparte_tareas_vencidas_sin_deposito_o_sin_suite(world, monkeypatch):
    ids = ready_tasks(world, 1)
    pending = create_task(world)["task_id"]  # suite sin preparar
    monkeypatch.setenv("DEMO_TRIAL_TASKS", f"{ids[0]},{pending}")
    chain = main.app.state.chain
    chain.deadline = chain.now + 60   # menos de 15 minutos de plazo
    assert world.get(f"/probar?address={FREELANCER}").status_code == 404
    chain.deadline, chain.status = chain.now + 3600, "Refunded"
    assert world.get(f"/probar?address={FREELANCER}").status_code == 404
    chain.status = "Funded"
    assert world.get(f"/probar?address={FREELANCER}").json()["task_id"] == ids[0]
