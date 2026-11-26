"""Creación y consulta de tareas por hitos (etapa 2, detrás de MILESTONES_ENABLED).

Todo sin red: cadena falsa en memoria. Comprueba que sin el flag todo se comporta
igual que antes y que con el flag se validan y guardan los hitos correctamente.
"""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ejecucion import cola
from backend.hashing import milestone_rules_hash, rules_hash
from backend.hitos import MAX_MILESTONE_DEADLINE_MINUTES
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore

CLIENT = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
FREELANCER = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
NOW = 1_000_000
INTERFACE = {
    "language": "python",
    "symbols": [{
        "module": "descuentos",
        "name": "aplicar_descuento",
        "kind": "function",
        "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]",
        "description": "Aplica descuento.",
    }],
}


class FakeChain:
    def __init__(self):
        self.now = NOW
        self.projects = {}
        self.tasks = {}
        self.project_reads = 0
        self.task_reads = 0

    def ledger_time(self):
        return self.now

    def has_usdc_trustline(self, address):
        return True

    def get_task(self, task_id):
        self.task_reads += 1
        return self.tasks.get(task_id)

    def get_project(self, task_id):
        self.project_reads += 1
        return self.projects.get(task_id)


def _milestones(n=3):
    return [
        {
            "title": f"Hito {i + 1}",
            "criteria": [f"Cumple requisito {i + 1}"],
            "amount": (i + 1) * 1_000_000,
            "deadline_minutes": (i + 1) * 60,
        }
        for i in range(n)
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("MILESTONES_ENABLED", raising=False)
    monkeypatch.delenv("MILESTONES_CONTRACT_ID", raising=False)
    monkeypatch.delenv("VERIFIER_ENABLED", raising=False)
    chain = FakeChain()
    main.app.state.store = StateStore(tmp_path / "state.json")
    main.app.state.queue = cola.MemoryQueue()
    main.app.state.chain = chain
    main.app.state.gemini = object()
    main.app.state.settings = type("S", (), {"gemini_model": "falso"})()
    return TestClient(main.app), chain


def test_sin_flag_rechaza_milestones_y_mantiene_tareas_simples(world):
    client, _ = world
    r = client.post("/tasks", json={
        "client_address": CLIENT,
        "description": DEMO_SPEC["description"],
        "language": "python",
        "milestones": _milestones(2),
    })
    assert r.status_code == 400 and r.json()["error"] == "INVALID_REQUEST"

    # Una tarea simple sigue funcionando igual y no trae clave `milestones`.
    ok = client.post("/tasks", json={
        "client_address": CLIENT, **DEMO_SPEC, "amount": 10_000_000, "deadline_minutes": 10,
    })
    assert ok.status_code == 200
    data = ok.json()
    assert "milestones" not in data
    assert data["rules_hash"] == rules_hash(DEMO_SPEC)

    # En tarea simple, deadline_minutes > 10080 sigue rechazándose.
    bad_dl = client.post("/tasks", json={
        "client_address": CLIENT, **DEMO_SPEC, "amount": 10_000_000, "deadline_minutes": 10_081,
    })
    assert bad_dl.status_code == 400 and bad_dl.json()["error"] == "INVALID_REQUEST"


def test_crear_tarea_por_hitos_suma_montos_y_calcula_hash_v3(world, monkeypatch):
    monkeypatch.setenv("MILESTONES_ENABLED", "true")
    monkeypatch.setenv("MILESTONES_CONTRACT_ID", "CAUBTDTWJKWKXH25LHXPES3ADTDRMBHYK4VOSWEWIBIYNLUINDR2K77K")
    client, chain = world

    ms = _milestones(3)
    r = client.post("/tasks", json={
        "client_address": CLIENT,
        "description": "Proyecto en tres partes",
        "language": "python",
        "allowed_deps": [],
        "examples": [],
        "milestones": ms,
        "sequential": True,
    })
    assert r.status_code == 200, r.text
    out = r.json()
    task_id = out["task_id"]
    assert out["amount"] == 6_000_000
    assert len(out["milestones"]) == 3

    saved = main.app.state.store.tasks[task_id]
    assert saved["amount"] == 6_000_000
    assert saved["deadline_minutes"] == 180
    assert saved["sequential"] is True
    assert saved["milestones_contract_id"] == "CAUBTDTWJKWKXH25LHXPES3ADTDRMBHYK4VOSWEWIBIYNLUINDR2K77K"

    for i, m in enumerate(saved["milestones"]):
        esperado = milestone_rules_hash(m["spec"], proyecto=task_id, indice=i, de=3, titulo=f"Hito {i + 1}")
        assert m["rules_hash"] == esperado
        assert out["milestones"][i]["rules_hash"] == esperado
        assert m["submissions"] == [] and m["cache"] == {} and m["codes"] == {}

    # GET /tasks/{id} lee get_project (nunca get_task).
    chain.projects[task_id] = {
        "task_id": task_id,
        "client": CLIENT,
        "freelancer": None,
        "milestones": [
            {"amount": m["amount"], "deadline": NOW + m["deadline_minutes"] * 60,
             "rules_hash": m["rules_hash"], "status": "Funded"}
            for m in saved["milestones"]
        ],
    }
    got = client.get(f"/tasks/{task_id}")
    assert got.status_code == 200
    body = got.json()
    assert chain.project_reads == 1 and chain.task_reads == 0
    assert body["amount"] == 6_000_000
    assert body["sequential"] is True
    assert len(body["milestones"]) == 3
    assert body["milestones"][0]["onchain"]["status"] == "Funded"
    assert body["milestones"][0]["seconds_left"] == 3600


def test_validaciones_al_crear_hitos(world, monkeypatch):
    monkeypatch.setenv("MILESTONES_ENABLED", "true")
    client, _ = world
    base = {"client_address": CLIENT, "description": "Desc", "language": "python"}

    # 1 hito y 11 hitos rechazados.
    assert client.post("/tasks", json={**base, "milestones": _milestones(1)}).status_code == 400
    assert client.post("/tasks", json={**base, "milestones": _milestones(11)}).status_code == 400

    # Plazo mayor a 28 días (40320 min) rechazado; 40320 exacto aceptado.
    bad_ms = _milestones(2)
    bad_ms[1]["deadline_minutes"] = MAX_MILESTONE_DEADLINE_MINUTES + 1
    assert client.post("/tasks", json={**base, "milestones": bad_ms}).status_code == 400

    ok_ms = _milestones(2)
    ok_ms[1]["deadline_minutes"] = MAX_MILESTONE_DEADLINE_MINUTES
    assert client.post("/tasks", json={**base, "milestones": ok_ms}).status_code == 200

    # Plazos decrecientes rechazados.
    dec_ms = _milestones(2)
    dec_ms[0]["deadline_minutes"] = 120
    dec_ms[1]["deadline_minutes"] = 60
    assert client.post("/tasks", json={**base, "milestones": dec_ms}).status_code == 400

    # Monto total distinto a la suma rechazado; igual a la suma aceptado.
    ms2 = _milestones(2)  # suma = 3_000_000
    assert client.post("/tasks", json={**base, "milestones": ms2, "amount": 9_999_999}).status_code == 400
    assert client.post("/tasks", json={**base, "milestones": ms2, "amount": 3_000_000}).status_code == 200

    # Float en monto de un hito rechazado.
    flt_ms = _milestones(2)
    flt_ms[0]["amount"] = 1.5
    assert client.post("/tasks", json={**base, "milestones": flt_ms}).status_code == 400


def test_hitos_con_ejecucion_encolan_suite_por_hito_y_accept_espera_todas(world, monkeypatch):
    monkeypatch.setenv("MILESTONES_ENABLED", "true")
    monkeypatch.setenv("VERIFIER_ENABLED", "true")
    client, _ = world

    r = client.post("/tasks", json={
        "client_address": CLIENT,
        "description": "Dos hitos ejecutables",
        "language": "python",
        "verification": "execution",
        "interface": INTERFACE,
        "milestones": _milestones(2),
    })
    assert r.status_code == 200, r.text
    out = r.json()
    task_id, invite = out["task_id"], out["invite_token"]
    assert [m["suite_status"] for m in out["milestones"]] == ["pendiente", "pendiente"]

    jobs = main.app.state.queue.for_task(task_id)
    assert len(jobs) == 2
    assert [j["payload"]["milestone"] for j in jobs] == [0, 1]

    # /accept bloquea hasta que las suites de TODOS los hitos estén listas.
    r_acc = client.post(f"/tasks/{task_id}/accept",
                        json={"freelancer_address": FREELANCER, "invite_token": invite})
    assert r_acc.status_code == 409 and r_acc.json()["error"] == "SUITE_NOT_READY"

    task = main.app.state.store.tasks[task_id]
    task["milestones"][0]["suite"]["status"] = "lista"
    r_acc2 = client.post(f"/tasks/{task_id}/accept",
                         json={"freelancer_address": FREELANCER, "invite_token": invite})
    assert r_acc2.status_code == 409 and r_acc2.json()["error"] == "SUITE_NOT_READY"

    task["milestones"][1]["suite"]["status"] = "lista"
    r_acc3 = client.post(f"/tasks/{task_id}/accept",
                         json={"freelancer_address": FREELANCER, "invite_token": invite})
    assert r_acc3.status_code == 200 and "freelancer_token" in r_acc3.json()

    # GET /tasks/{id}/suite?milestone=0 devuelve el plan del hito 0.
    s0 = client.get(f"/tasks/{task_id}/suite", params={"milestone": 0})
    assert s0.status_code == 200 and s0.json()["milestone"] == 0 and s0.json()["status"] == "lista"
