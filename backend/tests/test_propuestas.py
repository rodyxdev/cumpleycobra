"""Propuestas privadas: autorización, estados y regresión del flujo por invitación."""

import asyncio
import json
import time

import pytest

from backend import identidad, main
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore
from backend.stellar_client import StellarUnavailable
from backend.tests.test_reputacion import C1, C2, P1, P2, session, world  # noqa: F401


def create_task(world, address=C1):
    r = world.client.post("/tasks", json={"client_address": address, **DEMO_SPEC,
                                        "amount": 10_000_000, "deadline_minutes": 10})
    assert r.status_code == 200
    return r.json()


def send(world, task, programmer=P1, address=C1, token=None):
    return world.client.post("/propuestas", json={"task_id": task["task_id"], "programador": programmer},
                             headers={**session(address), "X-Client-Token": token or task["client_token"]})


def decision(world, proposal, action="aceptar", address=P1):
    return world.client.post(f"/propuestas/{proposal['id']}/{action}", headers=session(address))


def client_list(world, task, address=C1, token=None):
    return world.client.get(f"/tasks/{task['task_id']}/propuestas",
                            headers={**session(address), "X-Client-Token": token or task["client_token"]})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"] == code


def test_propuesta_completa_sin_exponer_tokens_y_persistencia(world):
    task = create_task(world)
    response = send(world, task)
    assert response.status_code == 200
    proposal = response.json()
    assert proposal["estado"] == "pendiente" and proposal["task_id"] == task["task_id"]
    assert set(proposal) == {"id", "task_id", "programador", "estado", "created_at"}
    assert client_list(world, task).json() == {"propuestas": [proposal]}
    assert StateStore(main.store().path).proposals[proposal["id"]] == proposal
    accepted = decision(world, proposal)
    assert accepted.status_code == 200 and accepted.json()["estado"] == "aceptada"
    saved = StateStore(main.store().path)
    assert accepted.json()["freelancer_token"] == saved.tasks[task["task_id"]]["freelancer_token"]
    assert saved.tasks[task["task_id"]]["freelancer_address"] == P1
    assert saved.proposals[proposal["id"]]["estado"] == "aceptada"
    assert client_list(world, task).json()["propuestas"][0]["estado"] == "aceptada"
    inbox = world.client.get("/buzon", headers=session(P1)).json()
    for token in (task["invite_token"], task["client_token"], accepted.json()["freelancer_token"]):
        assert token not in json.dumps(inbox) and token not in client_list(world, task).text


@pytest.mark.parametrize("address,token", [(C2, None), (P1, None), (C1, "incorrecto")])
def test_solo_cliente_con_sesion_y_token_correctos(world, address, token):
    task = create_task(world)
    assert_error(send(world, task, address=address, token=token), 403, "NOT_TASK_CLIENT")
    assert_error(client_list(world, task, address=address, token=token), 403, "NOT_TASK_CLIENT")
    assert main.store().proposals == {}


def test_token_de_otra_tarea_y_header_ausente_no_sirven(world):
    task, other = create_task(world), create_task(world)
    assert_error(send(world, task, token=other["client_token"]), 403, "NOT_TASK_CLIENT")
    r = world.client.post("/propuestas", json={"task_id": task["task_id"], "programador": P1}, headers=session(C1))
    assert_error(r, 403, "NOT_TASK_CLIENT")
    assert_error(world.client.get(f"/tasks/{task['task_id']}/propuestas", headers=session(C1)), 403, "NOT_TASK_CLIENT")


@pytest.mark.parametrize("auth", [None, "Bearer invalido", "expired"])
def test_todos_los_endpoints_exigen_sesion_vigente(world, auth):
    task = create_task(world)
    proposal = send(world, task).json()
    if auth == "expired":
        auth = "Bearer " + identidad.issue_session(main.auth_keys(), C1, now=time.time() - 50_000)["token"]
    headers = {"X-Client-Token": task["client_token"], **({"Authorization": auth} if auth else {})}
    requests = [
        ("post", "/propuestas", {"task_id": task["task_id"], "programador": P2}),
        ("get", "/buzon", None),
        ("get", f"/tasks/{task['task_id']}/propuestas", None),
        ("post", f"/propuestas/{proposal['id']}/aceptar", None),
        ("post", f"/propuestas/{proposal['id']}/rechazar", None),
    ]
    for method, path, body in requests:
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        assert_error(getattr(world.client, method)(path, **kwargs), 401, "SESSION_REQUIRED")
    assert main.store().proposals[proposal["id"]]["estado"] == "pendiente"


def test_duplicado_por_tarea_y_destinatario_incluso_rechazado(world):
    task = create_task(world)
    proposal = send(world, task).json()
    assert_error(send(world, task), 409, "PROPOSAL_EXISTS")
    assert decision(world, proposal, "rechazar").status_code == 200
    assert_error(send(world, task), 409, "PROPOSAL_EXISTS")
    assert send(world, task, programmer=P2).status_code == 200
    assert send(world, create_task(world)).status_code == 200


def test_buzon_filtra_antes_de_leer_la_cadena_y_usa_monto_onchain(world):
    one, two = create_task(world), create_task(world, C2)
    first = send(world, one).json()
    send(world, two, P2, C2)
    world.chain.onchain[one["task_id"]] = {"amount": 25_000_000, "status": "Funded"}
    before = world.chain.get_task_calls
    inbox = world.client.get("/buzon", headers=session(P1)).json()["propuestas"]
    assert len(inbox) == 1 and inbox[0]["id"] == first["id"]
    assert world.chain.get_task_calls == before + 1
    summary = inbox[0]["tarea"]
    assert summary["description"] == DEMO_SPEC["description"] and summary["criteria"] == DEMO_SPEC["criteria"]
    assert summary["amount"] == 10_000_000 and summary["onchain"] == {"amount": 25_000_000, "status": "Funded"}
    assert two["task_id"] not in json.dumps(inbox)
    assert world.client.get("/buzon", headers=session(C1)).json() == {"propuestas": []}


def test_buzon_sin_deposito_y_caida_rpc_no_inventan_estado(world):
    send(world, create_task(world))
    summary = world.client.get("/buzon", headers=session(P1)).json()["propuestas"][0]["tarea"]
    assert summary["onchain"] is None and summary["onchain_error"] is None
    world.chain.down = True
    summary = world.client.get("/buzon", headers=session(P1)).json()["propuestas"][0]["tarea"]
    assert summary["onchain"] is None and summary["onchain_error"]


@pytest.mark.parametrize("action", ["aceptar", "rechazar"])
@pytest.mark.parametrize("intruder", [C1, C2, P2])
def test_otra_direccion_no_decide(world, action, intruder):
    proposal = send(world, create_task(world)).json()
    assert_error(decision(world, proposal, action, intruder), 403, "NOT_PROPOSAL_RECIPIENT")
    assert main.store().proposals[proposal["id"]]["estado"] == "pendiente"


def test_rechazo_persistido_no_permite_aceptar_ni_amarrar(world):
    task = create_task(world)
    proposal = send(world, task).json()
    assert decision(world, proposal, "rechazar").json()["estado"] == "rechazada"
    assert decision(world, proposal, "rechazar").status_code == 200
    assert_error(decision(world, proposal), 409, "PROPOSAL_REJECTED")
    assert main.store().tasks[task["task_id"]]["freelancer_address"] is None
    assert client_list(world, task).json()["propuestas"][0]["estado"] == "rechazada"
    assert StateStore(main.store().path).proposals[proposal["id"]]["estado"] == "rechazada"


def test_tarea_tomada_por_otro_programador_no_admite_propuestas_ni_decisiones(world):
    task = create_task(world)
    proposal = send(world, task).json()
    world.client.post(f"/tasks/{task['task_id']}/accept", json={"freelancer_address": P2, "invite_token": task["invite_token"]})
    assert_error(send(world, task, programmer=P2), 409, "TASK_TAKEN")
    assert_error(decision(world, proposal), 409, "TASK_TAKEN")
    assert_error(decision(world, proposal, "rechazar"), 409, "TASK_TAKEN")
    assert main.store().proposals[proposal["id"]]["estado"] == "pendiente"


def test_acepto_por_invitacion_y_luego_la_propuesta_devuelve_el_mismo_token(world):
    task = create_task(world)
    proposal = send(world, task).json()
    by_invite = world.client.post(f"/tasks/{task['task_id']}/accept",
                                  json={"freelancer_address": P1, "invite_token": task["invite_token"]}).json()
    accepted = decision(world, proposal)
    assert accepted.status_code == 200
    assert accepted.json()["freelancer_token"] == by_invite["freelancer_token"]
    assert accepted.json()["estado"] == "aceptada"
    assert StateStore(main.store().path).proposals[proposal["id"]]["estado"] == "aceptada"
    assert_error(send(world, task, programmer=P2), 409, "TASK_TAKEN")
    assert_error(decision(world, proposal, "rechazar"), 409, "TASK_TAKEN")


def test_propuesta_pendiente_con_la_tarea_amarrada_a_su_destinatario_se_acepta(world):
    # accept() amarró la tarea pero el proceso cayó antes de guardar la propuesta como aceptada.
    task = create_task(world)
    proposal = send(world, task).json()
    stored = main.store().tasks[task["task_id"]]
    stored.update(freelancer_address=P1, freelancer_token="token-del-amarre", accepted_at=int(time.time()))
    main.store().save()
    main.app.state.store = StateStore(main.store().path)
    assert main.store().proposals[proposal["id"]]["estado"] == "pendiente"
    accepted = decision(world, proposal)
    assert accepted.status_code == 200 and accepted.json()["freelancer_token"] == "token-del-amarre"
    assert StateStore(main.store().path).proposals[proposal["id"]]["estado"] == "aceptada"


def test_propuesta_rechazada_sigue_sin_aceptarse_aunque_la_tarea_sea_suya(world):
    task = create_task(world)
    proposal = send(world, task).json()
    assert decision(world, proposal, "rechazar").status_code == 200
    world.client.post(f"/tasks/{task['task_id']}/accept", json={"freelancer_address": P1, "invite_token": task["invite_token"]})
    assert_error(decision(world, proposal), 409, "PROPOSAL_REJECTED")


def test_no_se_puede_enviar_una_propuesta_a_uno_mismo(world):
    task = create_task(world)
    r = send(world, task, programmer=C1)
    assert_error(r, 400, "INVALID_REQUEST")
    assert r.json()["message"] == "No puedes enviarte una propuesta a ti mismo"
    assert main.store().proposals == {}


def test_propuesta_aceptada_no_se_puede_rechazar_y_aceptar_de_nuevo_devuelve_el_mismo_token(world):
    task = create_task(world)
    proposal, other = send(world, task).json(), send(world, task, P2).json()
    first = decision(world, proposal)
    assert first.status_code == 200
    # Otro navegador o respuesta perdida: el destinatario recupera el mismo token sin reamarrar.
    again = decision(world, proposal)
    assert again.status_code == 200 and again.json() == first.json()
    assert main.store().tasks[task["task_id"]]["freelancer_token"] == first.json()["freelancer_token"]
    assert_error(decision(world, proposal, "rechazar"), 409, "TASK_TAKEN")
    assert main.store().proposals[proposal["id"]]["estado"] == "aceptada"
    # Nadie más obtiene el token: otra dirección con esta propuesta, ni otro destinatario con la suya.
    assert_error(decision(world, proposal, address=P2), 403, "NOT_PROPOSAL_RECIPIENT")
    assert_error(decision(world, other, address=P2), 409, "TASK_TAKEN")


@pytest.mark.parametrize("failure,status,code", [(False, 409, "NO_USDC_TRUSTLINE"), ("network", 502, "CHAIN_UNAVAILABLE")])
def test_fallos_de_accept_no_cambian_propuesta(world, monkeypatch, failure, status, code):
    task = create_task(world)
    proposal = send(world, task).json()
    def trustline(_):
        if failure == "network":
            raise StellarUnavailable("Horizon caído")
        return failure
    monkeypatch.setattr(world.chain, "has_usdc_trustline", trustline)
    assert_error(decision(world, proposal), status, code)
    assert main.store().tasks[task["task_id"]]["freelancer_address"] is None
    assert main.store().proposals[proposal["id"]]["estado"] == "pendiente"


def test_reutiliza_funcion_accept_y_la_ruta_original_responde_igual(world, monkeypatch):
    task = create_task(world)
    proposal = send(world, task).json()
    original, calls = main.accept, []
    async def observed(task_id, body):
        calls.append((task_id, body))
        return await original(task_id, body)
    monkeypatch.setattr(main, "accept", observed)
    accepted = decision(world, proposal).json()
    assert len(calls) == 1 and calls[0][0] == task["task_id"]
    assert calls[0][1].invite_token == task["invite_token"]
    # Idempotencia y estructura originales, sin sesión de identidad en /accept.
    old = world.client.post(f"/tasks/{task['task_id']}/accept", json={"freelancer_address": P1, "invite_token": task["invite_token"]})
    assert old.status_code == 200 and old.json() == {"freelancer_token": accepted["freelancer_token"]}
    wrong = world.client.post(f"/tasks/{task['task_id']}/accept", json={"freelancer_address": P1, "invite_token": "incorrecta"})
    assert_error(wrong, 403, "INVALID_TOKEN")
    taken = world.client.post(f"/tasks/{task['task_id']}/accept", json={"freelancer_address": P2, "invite_token": task["invite_token"]})
    assert_error(taken, 409, "TASK_TAKEN")
    fresh = create_task(world)
    first = world.client.post(f"/tasks/{fresh['task_id']}/accept", json={"freelancer_address": P1, "invite_token": fresh["invite_token"]})
    assert first.status_code == 200 and set(first.json()) == {"freelancer_token"}
    monkeypatch.setattr(world.chain, "has_usdc_trustline", lambda _: False)
    no_line = world.client.post(f"/tasks/{fresh['task_id']}/accept", json={"freelancer_address": P1, "invite_token": fresh["invite_token"]})
    assert_error(no_line, 409, "NO_USDC_TRUSTLINE")


def test_dos_propuestas_concurrentes_solo_una_amarra(world):
    task = create_task(world)
    one, two = send(world, task).json(), send(world, task, P2).json()
    async def race():
        return await asyncio.gather(main.accept_proposal(one["id"], session(P1)["Authorization"]),
                                    main.accept_proposal(two["id"], session(P2)["Authorization"]), return_exceptions=True)
    results = asyncio.run(race())
    assert sum(isinstance(r, dict) for r in results) == 1
    errors = [r for r in results if isinstance(r, main.ApiError)]
    assert len(errors) == 1 and errors[0].code == "TASK_TAKEN"
    assert sum(p["estado"] == "aceptada" for p in main.store().proposals.values()) == 1


def test_propuesta_compite_con_invitacion_sin_cambiar_destinatario(world):
    task = create_task(world)
    proposal = send(world, task).json()
    async def race():
        return await asyncio.gather(main.accept(task["task_id"], main.AcceptIn(freelancer_address=P2, invite_token=task["invite_token"])),
                                    main.accept_proposal(proposal["id"], session(P1)["Authorization"]), return_exceptions=True)
    results = asyncio.run(race())
    assert isinstance(results[0], dict)
    assert isinstance(results[1], main.ApiError) and results[1].code == "TASK_TAKEN"
    assert main.store().tasks[task["task_id"]]["freelancer_address"] == P2


def test_creacion_concurrente_no_duplica(world):
    task = create_task(world)
    async def race():
        return await asyncio.gather(*(main.create_proposal(main.ProposalIn(task_id=task["task_id"], programador=P1),
                                                          task["client_token"], session(C1)["Authorization"]) for _ in range(2)),
                                    return_exceptions=True)
    results = asyncio.run(race())
    assert sum(isinstance(r, dict) for r in results) == 1
    assert next(r for r in results if isinstance(r, main.ApiError)).code == "PROPOSAL_EXISTS"


@pytest.mark.parametrize("body", [{}, {"task_id": "", "programador": P1}, {"task_id": "x", "programador": 4},
                                   {"task_id": "x", "programador": P1, "extra": True}])
def test_entrada_estricta(world, body):
    assert_error(world.client.post("/propuestas", json=body, headers=session(C1)), 400, "INVALID_REQUEST")


def test_direccion_invalida_y_recursos_inexistentes(world):
    task = create_task(world)
    assert_error(send(world, task, programmer="no-es-direccion"), 400, "INVALID_REQUEST")
    assert_error(send(world, {**task, "task_id": "no-existe"}), 404, "TASK_NOT_FOUND")
    for action in ("aceptar", "rechazar"):
        assert_error(decision(world, {"id": "no-existe"}, action), 404, "PROPOSAL_NOT_FOUND")


def test_estado_anterior_sin_propuestas_sigue_cargando(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"version":1,"tasks":{}}', encoding="utf-8")
    assert StateStore(p).proposals == {}


def test_buzon_en_paralelo_con_limite_y_cache_terminal_da_el_mismo_resultado(world, monkeypatch):
    import threading
    tasks = [create_task(world) for _ in range(12)]
    for i, t in enumerate(tasks):
        send(world, t)
        status = ("Released", "Refunded", "Funded", None)[i % 4]
        if status:
            world.chain.onchain[t["task_id"]] = {"amount": 10_000_000 + i, "status": status}
    world.chain.onchain[tasks[5]["task_id"]] = "caida"  # una lectura falla: solo esa trae el error
    active, peak, lock, calls = 0, 0, threading.Lock(), []

    def get_task(task_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(task_id)
        try:
            time.sleep(0.05)
            value = world.chain.onchain.get(task_id)
            if value == "caida":
                raise StellarUnavailable("RPC caído")
            return value
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(world.chain, "get_task", get_task)

    # Resultado esperado, armado en serie con la misma forma de antes.
    expected = []
    for p in reversed(list(main.store().proposals.values())):
        t = main.store().tasks[p["task_id"]]
        oc = world.chain.onchain.get(p["task_id"])
        down = oc == "caida"
        expected.append({**main.public_proposal(p), "tarea": {
            "description": t["spec"]["description"], "criteria": list(t["spec"]["criteria"]),
            "amount": t["amount"], "freelancer_address": t["freelancer_address"],
            "onchain": {"amount": oc["amount"], "status": oc["status"]} if oc and not down else None,
            "onchain_error": "No se pudo leer el contrato (RPC caído)" if down else None,
        }})

    first = world.client.get("/buzon", headers=session(P1)).json()["propuestas"]
    assert first == expected
    assert 1 < peak <= main.ONCHAIN_CONCURRENCY and len(calls) == 12
    calls.clear()
    second = world.client.get("/buzon", headers=session(P1)).json()["propuestas"]
    assert second == expected
    terminal = {t["task_id"] for i, t in enumerate(tasks) if i % 4 in (0, 1) and i != 5}
    # Released y Refunded no se vuelven a leer; Funded, sin depósito y la caída sí.
    assert not terminal & set(calls) and len(calls) == 12 - len(terminal)
