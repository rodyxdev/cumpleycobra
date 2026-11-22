"""Verificación por ejecución (fase 3): hashes, suite, regla final, cola y el flujo de la API.

El modelo es falso (devuelve tests fijos y un juez que siempre dice «pass») para comprobar que la
regla determinista y las señales mandan sobre el juez. El contrato también es falso. Las pruebas
de punta a punta corren el trabajador real contra Docker, a través del TestClient.
"""

import base64
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ejecucion import cola, juez, regla
from backend.ejecucion import suite as suite_mod
from backend.ejecucion.seguridad import security_scan
from backend.ejecucion.senales import collect_signals, load_sources
from backend.hashing import rules_hash, verdict_hash_v2
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore
from backend.stellar_client import ReleaseOutcome

CLIENT = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
FREELANCER = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
AMOUNT = 10_000_000
NOW = 1_000_000
QUEUE_TOKEN = "token-de-la-cola-para-tests"
CASOS = Path(main.__file__).resolve().parent / "casos"

INTERFACE = {"language": "python", "symbols": [{
    "module": "descuentos", "name": "aplicar_descuento", "kind": "function",
    "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]",
    "description": "Devuelve cada precio con el descuento aplicado, redondeado a 2 decimales."}]}
EXEC_SPEC = {**DEMO_SPEC, "verification": "execution", "interface": INTERFACE}

HEADER = 'from cc_channel import remote\n\naplicar_descuento = remote("descuentos", "aplicar_descuento")\n\n'
TESTS = {
    1: HEADER + 'def test_existe_y_responde():\n    """La función existe y devuelve una lista."""\n'
                '    assert aplicar_descuento([10.0], 0.0) == [10.0]\n',
    2: HEADER + 'def test_formula():\n    """Aplica precio * (1 - porcentaje / 100)."""\n'
                '    assert aplicar_descuento([200.0, 80.0], 25.0) == [150.0, 60.0]\n\n'
                'def test_ejemplo():\n    """Ejemplo público."""\n'
                '    assert aplicar_descuento([100.0, 50.0], 10.0) == [90.0, 45.0]\n',
    3: HEADER + 'def test_redondeo():\n    """Redondea a 2 decimales."""\n'
                '    assert aplicar_descuento([19.99], 15.0) == [16.99]\n'
                '    assert aplicar_descuento([10.0], 33.333) == [6.67]\n',
    4: HEADER + 'def test_vacia():\n    """Lista vacía."""\n    assert aplicar_descuento([], 20.0) == []\n\n'
                'def test_orden():\n    """Conserva orden y cantidad."""\n'
                '    assert aplicar_descuento([1.0, 2.0, 3.0], 0.0) == [1.0, 2.0, 3.0]\n',
    6: HEADER + 'def test_termina():\n    """Termina con varias entradas."""\n'
                '    assert aplicar_descuento([5.0, 5.0, 5.0, 5.0], 50.0) == [2.5, 2.5, 2.5, 2.5]\n',
}


def generated(index: int) -> suite_mod.GeneratedCriterion:
    if index in TESTS:
        return suite_mod.GeneratedCriterion(tipo="test", motivo="se comprueba llamando", plan=["una frase"],
                                            code=TESTS[index])
    return suite_mod.GeneratedCriterion(tipo="lectura", motivo="se ve en el código", plan=[], code="")


def judge_all_pass(n: int) -> juez.JudgeOutput:
    return juez.JudgeOutput(
        criteria=[juez.JudgeCriterion(numero=i, verdict="pass", reasoning="cumple", evidence=[]) for i in range(1, n + 1)],
        injection_detected=False, injection_evidence=[], cheating_detected=False, cheating_evidence=[],
        summary="todo bien")


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {"suite": 0, "juez": 0}

    async def fake_structured(role, system, turns, output, **kw):
        calls[role] += 1
        if output is suite_mod.ReferenceImplementation:
            calls["referencia"] = calls.get("referencia", 0) + 1
            return suite_mod.ReferenceImplementation(modules=[suite_mod.ReferenceModule(
                module="descuentos", code=(CASOS / "a_feliz.py").read_text(encoding="utf-8"))])
        if role == "suite":
            import json
            index = json.loads(turns[0]["content"])["criterio_objetivo"]
            return generated(index)
        return judge_all_pass(len(DEMO_SPEC["criteria"]))

    monkeypatch.setattr(suite_mod, "structured", fake_structured)
    monkeypatch.setattr(juez, "structured", fake_structured)
    return calls


# --- hashes ------------------------------------------------------------------------------

def test_rules_hash_v1_no_cambia_y_v2_incluye_interfaz():
    assert rules_hash(DEMO_SPEC) == "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
    v2 = rules_hash(EXEC_SPEC)
    assert v2 != rules_hash(DEMO_SPEC)
    otra = {**EXEC_SPEC, "interface": {**INTERFACE, "symbols": [{**INTERFACE["symbols"][0], "name": "otra"}]}}
    assert rules_hash(otra) != v2


def test_verdict_hash_v2_es_determinista_y_sensible():
    kw = dict(task_id="t", rules_hash="r", suite_hash="s", workspace_hash="sha256:" + "0" * 64,
              approved=True, stage="final", criteria=[{"index": 1, "status": "pass"}], video_url=None)
    assert verdict_hash_v2(**kw) == verdict_hash_v2(**kw)
    assert verdict_hash_v2(**kw) != verdict_hash_v2(**{**kw, "approved": False})
    assert verdict_hash_v2(**kw) != verdict_hash_v2(**{**kw, "suite_hash": "otra"})


# --- suite -------------------------------------------------------------------------------

def run(outcomes, report=True):
    return {"report_found": report, "outcomes": outcomes, "stderr_tail": ""}


def outcome(file, name, result):
    return {"nodeid": f"{file}::{name}", "file": file, "name": name, "outcome": result, "message": ""}


def test_validacion_rechaza_un_test_que_pasa_contra_el_stub():
    f = "test_c2.py"
    problems = suite_mod.validation_problems(f, run([outcome(f, "test_a", "failed")]),
                                             run([outcome(f, "test_a", "passed")]))
    assert any("PASA contra la entrega stub" in p for p in problems)
    assert suite_mod.validation_problems(f, run([outcome(f, "test_a", "error")]),
                                         run([outcome(f, "test_a", "failed")])) == []
    assert "no colectó" in suite_mod.validation_problems(f, run([]), run([]))[0]


def test_tests_generados_solo_importan_lo_permitido():
    assert suite_mod.static_problems(TESTS[2]) == []
    assert "importa 'os'" in suite_mod.static_problems("import os\n\ndef test_a():\n    assert 1\n")[0]
    assert suite_mod.static_problems("x = 1\n") == ["no define ninguna función test_ a nivel de módulo"]


def test_suite_hash_cubre_tests_y_clasificacion():
    suite = suite_mod.new_suite_state(EXEC_SPEC)
    for c in suite["criteria"]:
        g = generated(c["index"])
        c.update(tipo=g.tipo, accepted=True)
        if g.code:
            suite["files"][suite_mod.test_filename(c["index"])] = g.code
    suite_mod.finalize(suite)
    first = suite["suite_hash"]
    suite["criteria"][4]["tipo"] = "test"
    suite_mod.finalize(suite)
    assert suite["status"] == "lista" and suite["suite_hash"] != first


# --- regla final -------------------------------------------------------------------------

def ready_suite():
    suite = suite_mod.new_suite_state(EXEC_SPEC)
    for c in suite["criteria"]:
        g = generated(c["index"])
        c.update(tipo=g.tipo, accepted=True, plan=g.plan)
        if g.code:
            suite["files"][suite_mod.test_filename(c["index"])] = g.code
    suite_mod.finalize(suite)
    return suite


def all_outcomes(result="passed"):
    return {i: [outcome(f"test_c{i}.py", "test_x", result)] for i in TESTS}


def decide(**kw):
    base = dict(suite=ready_suite(), hygiene={"blockers": []}, build=None, security_problems=[], signals=[],
                outcomes=all_outcomes(), test_run_error=None, judge=judge_all_pass(6), judge_error=None,
                checker=juez.EvidenceChecker(EXEC_SPEC, {}, {}, []))
    return regla.decide(**{**base, **kw})


def test_regla_aprueba_solo_con_tests_y_juez():
    d = decide()
    assert d.approved and d.stage == "final"
    assert all(c.startswith("✓") for c in d.comparison())


def test_un_test_que_falla_rechaza_aunque_el_juez_diga_pass():
    outcomes = all_outcomes()
    outcomes[3] = [outcome("test_c3.py", "test_redondeo", "failed")]
    d = decide(outcomes=outcomes)
    assert not d.approved and d.status == "rejected" and d.stage == "tests"
    assert d.comparison()[2].startswith("✗ Criterio 3")


def test_juez_caido_deja_revision_manual():
    d = decide(judge=None, judge_error="sin respuesta")
    assert not d.approved and d.status == "manual_review"


def test_senal_de_inyeccion_impide_aprobar():
    files = {"descuentos.py": (CASOS / "c_inyeccion.py").read_text(encoding="utf-8")}
    signals = collect_signals(load_sources(files), DEMO_SPEC["examples"])
    assert any(s.kind == "injection" for s in signals)
    d = decide(signals=signals)
    assert not d.approved and d.flags["injection"] and d.security_flags


def test_capa_de_seguridad_de_v1_rechaza_secretos():
    files = {"descuentos.py": (CASOS / "d_secretos.py").read_text(encoding="utf-8")}
    problems = security_scan(files, [])
    assert problems
    d = decide(security_problems=problems)
    assert not d.approved and d.stage == "static"


def test_seguridad_permite_modulos_propios_e_ignora_tests_propios():
    files = {"descuentos.py": "from util import factor\n", "util.py": "def factor(p):\n    return 1 - p / 100\n",
             "tests/test_mio.py": "import pytest\n"}
    assert security_scan(files, []) == []


def test_trampa_con_ejemplos_publicos_se_senala():
    code = "def aplicar_descuento(precios, porcentaje):\n    if precios == [100.0, 50.0]:\n        return [90.0, 45.0]\n"
    signals = collect_signals(load_sources({"descuentos.py": code}), DEMO_SPEC["examples"])
    assert any(s.kind == "cheating" for s in signals)


def test_cita_inventada_del_juez_no_cuenta():
    checker = juez.EvidenceChecker(EXEC_SPEC, {"descuentos.py": "x = 1\n"}, {}, [])
    assert checker.is_valid(juez.Evidence(kind="code", ref="descuentos.py:1", quote="x = 1"))
    assert not checker.is_valid(juez.Evidence(kind="code", ref="descuentos.py:1", quote="return 42"))


# --- cola --------------------------------------------------------------------------------

def test_cola_en_memoria_reclama_una_vez_y_respeta_el_lease(monkeypatch):
    q = cola.MemoryQueue()
    job = q.enqueue("verify", "t1", {"a": 1})
    claimed = q.claim()
    assert claimed["id"] == job["id"] and q.claim() is None
    with pytest.raises(cola.LeaseError):
        q.progress(job["id"], "otro-lease", {"stage": "x"})
    q.progress(job["id"], claimed["lease_id"], {"stage": "tests", "detail": "d"})
    done = q.finish(job["id"], claimed["lease_id"], "done", {"ok": True})
    assert done["status"] == "done" and done["progress"][0]["stage"] == "tests"
    with pytest.raises(cola.LeaseError):
        q.finish(job["id"], claimed["lease_id"], "done", {})


def test_cola_devuelve_el_trabajo_si_vence_el_plazo(monkeypatch):
    q = cola.MemoryQueue()
    job = q.enqueue("suite", "t1", {})
    q.claim()
    clock = [cola.time.time() + cola.LEASE_SECS + 1]
    monkeypatch.setattr(cola.time, "time", lambda: clock[0])
    again = q.claim()
    assert again["id"] == job["id"] and again["attempts"] == 2
    for _ in range(cola.MAX_ATTEMPTS):
        clock[0] += cola.LEASE_SECS + 1
        q.claim()
    clock[0] += cola.LEASE_SECS + 1
    assert q.get(job["id"])["status"] == "failed"


# --- flujo de la API ---------------------------------------------------------------------

class FakeChain:
    def __init__(self, rules):
        self.now, self.status, self.deadline, self.rules = NOW, "Funded", NOW + 3600, rules
        self.onchain_freelancer = None
        self.releases = []

    def has_usdc_trustline(self, address):
        return True

    def ledger_time(self):
        return self.now

    def transaction_succeeded(self, tx):
        return True

    def get_task(self, task_id):
        return {"task_id": task_id, "client": CLIENT, "amount": AMOUNT, "deadline": self.deadline,
                "rules_hash": self.rules, "status": self.status, "freelancer": self.onchain_freelancer}

    def release(self, task_id, freelancer, ch, vh, on_signed):
        self.releases.append((ch, vh))
        on_signed("bb" * 32)
        self.status, self.onchain_freelancer = "Released", FREELANCER
        return ReleaseOutcome("success", "bb" * 32)


@pytest.fixture
def world(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("VERIFIER_ENABLED", "true")
    monkeypatch.setenv("VERIFIER_QUEUE_TOKEN", QUEUE_TOKEN)
    main.app.state.store = StateStore(tmp_path / "state.json")
    main.app.state.queue = cola.MemoryQueue()
    main.app.state.chain = FakeChain(rules_hash(EXEC_SPEC))
    main.app.state.gemini = object()
    main.app.state.settings = type("S", (), {"gemini_model": "falso"})()
    return TestClient(main.app)


def create_task(client):
    body = {"client_address": CLIENT, **DEMO_SPEC, "amount": AMOUNT, "deadline_minutes": 60,
            "verification": "execution", "interface": INTERFACE}
    r = client.post("/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def worker_headers():
    return {"Authorization": f"Bearer {QUEUE_TOKEN}"}


def test_sin_flag_no_hay_ejecucion(tmp_path, monkeypatch, fake_llm):
    monkeypatch.delenv("VERIFIER_ENABLED", raising=False)
    main.app.state.store = StateStore(tmp_path / "state.json")
    main.app.state.queue = cola.MemoryQueue()
    client = TestClient(main.app)
    r = client.post("/tasks", json={"client_address": CLIENT, **DEMO_SPEC, "amount": AMOUNT,
                                    "deadline_minutes": 60, "verification": "execution", "interface": INTERFACE})
    assert r.status_code == 400
    assert client.post("/verifier/claim", headers=worker_headers()).status_code == 404


def test_rutas_del_trabajador_exigen_el_token(world):
    assert world.post("/verifier/claim").status_code == 403
    assert world.post("/verifier/claim", headers={"Authorization": "Bearer otro"}).status_code == 403


def test_aceptar_exige_la_suite_lista(world):
    created = create_task(world)
    assert created["rules_hash"] == rules_hash(EXEC_SPEC) and created["suite_status"] == "pendiente"
    r = world.post(f"/tasks/{created['task_id']}/accept",
                   json={"freelancer_address": FREELANCER, "invite_token": created["invite_token"]})
    assert r.status_code == 409 and r.json()["error"] == "SUITE_NOT_READY"


def drive_suite(client, task_id, stub_passes=False, reference_fails=(), steps=None):
    """Hace de trabajador para el trabajo de suite, con resultados fabricados.

    `reference_fails`: archivos que fallan contra la referencia en la primera ronda; "*" = todos
    (referencia rota). `steps` recibe cada paso de validación.
    """
    job = client.post("/verifier/claim", headers=worker_headers()).json()
    assert job["kind"] == "suite"
    step = client.post(f"/verifier/jobs/{job['id']}/suite/generate", headers=worker_headers(),
                       json={"lease_id": job["lease_id"]}).json()
    rounds = 0
    while step["next"] == "validate":
        rounds += 1
        if steps is not None:
            steps.append(step)
        outs = [outcome(f, "test_x", "failed") for f in step["tests"]]
        stub = [outcome(f, "test_x", "passed" if stub_passes else "failed") for f in step["tests"]]
        fails = set(step["tests"]) if "*" in reference_fails else set(reference_fails)
        ref = [outcome(f, "test_x", "failed" if rounds == 1 and f in fails else "passed") for f in step["tests"]]
        step = client.post(f"/verifier/jobs/{job['id']}/suite/validation", headers=worker_headers(),
                           json={"lease_id": job["lease_id"], "empty": run(outs), "stub": run(stub),
                                 "reference": run(ref) if step.get("reference") else None}).json()
    return rounds


def test_suite_se_regenera_y_se_rechaza_si_nunca_valida(world, fake_llm):
    created = create_task(world)
    rounds = drive_suite(world, created["task_id"], stub_passes=True)
    assert rounds == 1 + suite_mod.MAX_REGENERATIONS
    plan = world.get(f"/tasks/{created['task_id']}/suite").json()
    assert plan["status"] == "rechazada" and plan["suite_hash"] is None
    # el criterio de lectura no se regenera; la referencia se genera una vez
    assert fake_llm["suite"] == 6 + 5 * suite_mod.MAX_REGENERATIONS + 1


def test_un_test_que_falla_contra_la_referencia_se_regenera(world, fake_llm):
    created = create_task(world)
    steps = []
    rounds = drive_suite(world, created["task_id"], reference_fails={"test_c3.py"}, steps=steps)
    assert rounds == 2 and steps[0]["reference"][0]["module"] == "descuentos"
    task = main.app.state.store.tasks[created["task_id"]]
    assert task["suite"]["status"] == "lista"
    assert [c["attempts"] for c in task["suite"]["criteria"]] == [1, 1, 2, 1, 1, 1]
    assert set(steps[1]["tests"]) == {f"test_c{i}.py" for i in TESTS}
    assert "referencia.json" in suite_mod.hashed_files(task["suite"])


def test_una_referencia_rota_no_culpa_a_los_tests(world, fake_llm):
    created = create_task(world)
    rounds = drive_suite(world, created["task_id"], reference_fails={"*"})
    task = main.app.state.store.tasks[created["task_id"]]
    assert rounds == 2 and task["suite"]["status"] == "lista"
    assert [c["attempts"] for c in task["suite"]["criteria"]] == [1, 1, 1, 1, 1, 1]  # no se regeneró ningún test
    assert fake_llm["referencia"] == 2


def test_validacion_exige_pasar_contra_la_referencia():
    f = "test_c2.py"
    ref = {"report_found": True, "outcomes": [outcome(f, "test_a", "passed"), {**outcome(f, "test_b", "failed"),
                                                                                "message": "assert [19.47] == [19.48]"}]}
    problems = suite_mod.validation_problems(f, run([outcome(f, "test_a", "failed")]), run([outcome(f, "test_a", "failed")]), ref)
    assert len(problems) == 1 and "FALLA contra una implementación correcta" in problems[0] and "19.47" in problems[0]


def test_si_el_verificador_falla_la_suite_se_reintenta_sin_regenerar(world, fake_llm):
    created = create_task(world)
    tid = created["task_id"]
    job = world.post("/verifier/claim", headers=worker_headers()).json()
    step = world.post(f"/verifier/jobs/{job['id']}/suite/generate", headers=worker_headers(),
                      json={"lease_id": job["lease_id"]}).json()
    assert step["next"] == "validate"
    calls = fake_llm["suite"]
    world.post(f"/verifier/jobs/{job['id']}/fail", headers=worker_headers(),
               json={"lease_id": job["lease_id"], "message": "docker no disponible"})
    rounds = drive_suite(world, tid)  # otro trabajo: reanuda la validación de la misma ronda
    assert rounds == 1 and fake_llm["suite"] == calls
    assert main.app.state.store.tasks[tid]["suite"]["status"] == "lista"


def test_tres_fallas_del_verificador_rechazan_la_suite(world):
    created = create_task(world)
    for _ in range(3):
        job = world.post("/verifier/claim", headers=worker_headers()).json()
        world.post(f"/verifier/jobs/{job['id']}/fail", headers=worker_headers(),
                   json={"lease_id": job["lease_id"], "message": "docker no disponible"})
    plan = world.get(f"/tasks/{created['task_id']}/suite").json()
    assert plan["status"] == "rechazada"
    assert world.post("/verifier/claim", headers=worker_headers()).status_code == 204


def test_el_plan_publico_nunca_trae_el_codigo_de_los_tests(world):
    created = create_task(world)
    drive_suite(world, created["task_id"])
    task = world.get(f"/tasks/{created['task_id']}").json()
    assert task["suite"]["status"] == "lista" and task["verification"] == "execution"
    assert "remote(" not in str(task) and "remote(" not in str(world.get(f"/tasks/{created['task_id']}/suite").json())
    assert [c["tipo"] for c in task["suite"]["criteria"]] == ["test", "test", "test", "test", "lectura", "test"]


def accepted_task(client):
    created = create_task(client)
    drive_suite(client, created["task_id"])
    ft = client.post(f"/tasks/{created['task_id']}/accept", json={
        "freelancer_address": FREELANCER, "invite_token": created["invite_token"]}).json()["freelancer_token"]
    return created, ft


def submit(client, task_id, ft, source):
    return client.post(f"/tasks/{task_id}/verificaciones", headers={"X-Freelancer-Token": ft},
                       json={"freelancer_address": FREELANCER, "source": source})


def test_evaluate_no_acepta_tareas_por_ejecucion(world):
    created, ft = accepted_task(world)
    r = world.post("/evaluate", headers={"X-Freelancer-Token": ft},
                   json={"task_id": created["task_id"], "freelancer_address": FREELANCER, "code": "x = 1"})
    assert r.status_code == 409 and r.json()["error"] == "EXECUTION_TASK"


def test_una_verificacion_a_la_vez_y_guardias(world):
    created, ft = accepted_task(world)
    tid = created["task_id"]
    assert submit(world, tid, "otro", {"kind": "code", "code": "x = 1"}).status_code == 403
    r = submit(world, tid, ft, {"kind": "code", "code": "x = 1"})
    assert r.status_code == 202
    again = submit(world, tid, ft, {"kind": "code", "code": "x = 2"})
    assert again.status_code == 409 and again.json()["error"] == "VERIFICATION_IN_PROGRESS"
    status = world.get(f"/verificaciones/{r.json()['verification_id']}", headers={"X-Client-Token": created["client_token"]})
    assert status.status_code == 200 and status.json()["status"] == "queued"
    assert world.get(f"/verificaciones/{r.json()['verification_id']}").status_code == 403


def test_resultado_fabricado_aprueba_y_paga(world):
    created, ft = accepted_task(world)
    tid = created["task_id"]
    vid = submit(world, tid, ft, {"kind": "code", "code": (CASOS / "a_feliz.py").read_text(encoding="utf-8")}).json()["verification_id"]
    job = world.post("/verifier/claim", headers=worker_headers()).json()
    assert job["id"] == vid and set(job["payload"]["tests"]) == {f"test_c{i}.py" for i in TESTS}
    outcomes = [outcome(f"test_c{i}.py", "test_x", "passed") for i in TESTS]
    evidence = {"workspace_hash": "sha256:" + "ab" * 32, "files": {"descuentos.py": (CASOS / "a_feliz.py").read_text(encoding="utf-8")},
                "hygiene": {"blockers": [], "warnings": [], "requirements": []}, "build": None,
                "tests": {"report_found": True, "outcomes": outcomes, "timed_out": False}}
    assert world.post(f"/verifier/jobs/{vid}/result", headers=worker_headers(),
                      json={"lease_id": job["lease_id"], "evidence": evidence}).status_code == 200
    status = world.get(f"/verificaciones/{vid}", headers={"X-Freelancer-Token": ft}).json()
    res = status["result"]
    assert status["status"] == "done" and res["approved"] is True and res["transaction_hash"] == "bb" * 32
    assert res["code_hash"] == "ab" * 32 and res["verdict_version"] == 2
    assert main.app.state.chain.releases == [("ab" * 32, res["verdict_hash"])]
    assert len(main.app.state.store.tasks[tid]["submissions"]) == 1


# --- de punta a punta con Docker -------------------------------------------------------

def docker_ok():
    from verifier.sandbox import docker_available
    return docker_available()


requires_docker = pytest.mark.skipif(not docker_ok(), reason="Docker no está disponible")


def worker_api(client):
    from verifier import worker

    api = worker.Api("http://testserver", QUEUE_TOKEN)
    api.http = client
    client.headers.update(worker_headers())
    return worker, api


def run_worker_once(client):
    worker, api = worker_api(client)
    raw = api.post("/verifier/claim", {})
    assert raw is not None
    worker.handle(worker.Job(api, raw))


@requires_docker
@pytest.mark.parametrize("caso,aprobado,etapa", [
    ("a_feliz.py", True, "final"),
    ("b_calidad.py", False, "tests"),
    ("c_inyeccion.py", False, "final"),
    ("d_secretos.py", False, "static"),
])
def test_casos_de_la_demo_ejecutando_de_verdad(world, monkeypatch, caso, aprobado, etapa):
    monkeypatch.setenv("CALL_TIMEOUT_S", "2")
    created = create_task(world)
    tid = created["task_id"]
    run_worker_once(world)  # suite: valida contra la entrega vacía y el stub, con Docker real
    assert world.get(f"/tasks/{tid}/suite").json()["status"] == "lista"
    world.headers.pop("Authorization", None)
    ft = world.post(f"/tasks/{tid}/accept", json={"freelancer_address": FREELANCER,
                                                   "invite_token": created["invite_token"]}).json()["freelancer_token"]
    vid = submit(world, tid, ft, {"kind": "code", "code": (CASOS / caso).read_text(encoding="utf-8")}).json()["verification_id"]
    run_worker_once(world)
    world.headers.pop("Authorization", None)
    status = world.get(f"/verificaciones/{vid}", headers={"X-Freelancer-Token": ft}).json()
    res = status["result"]
    assert res["approved"] is aprobado, res["reason"]
    assert res["stage"] == etapa, res["reason"]
    assert bool(res["transaction_hash"]) is aprobado
    stages = [p["stage"] for p in status["progress"]]
    assert stages[:3] == ["ingesta", "higiene", "tests"]


@requires_docker
def test_entrega_por_zip_con_varios_archivos(world, monkeypatch):
    monkeypatch.setenv("CALL_TIMEOUT_S", "2")
    created = create_task(world)
    tid = created["task_id"]
    run_worker_once(world)
    world.headers.pop("Authorization", None)
    ft = world.post(f"/tasks/{tid}/accept", json={"freelancer_address": FREELANCER,
                                                   "invite_token": created["invite_token"]}).json()["freelancer_token"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("proyecto/descuentos.py", "from calculo import factor\n\n\ndef aplicar_descuento(precios, porcentaje):\n"
                    "    return [round(p * factor(porcentaje), 2) for p in precios]\n")
        zf.writestr("proyecto/calculo.py", "def factor(porcentaje):\n    return 1 - porcentaje / 100\n")
    r = submit(world, tid, ft, {"kind": "zip", "zip_b64": base64.b64encode(buf.getvalue()).decode()})
    assert r.status_code == 202, r.text
    run_worker_once(world)
    world.headers.pop("Authorization", None)
    res = world.get(f"/verificaciones/{r.json()['verification_id']}", headers={"X-Freelancer-Token": ft}).json()["result"]
    assert res["approved"] is True, res["reason"]
    delivery = main.app.state.store.tasks[tid]["codes"][res["code_hash"]]
    assert set(delivery["files"]) == {"descuentos.py", "calculo.py"}


@pytest.mark.skipif(not __import__("os").environ.get("CYC_TEST_DATABASE_URL"), reason="sin CYC_TEST_DATABASE_URL")
def test_cola_en_postgres_no_entrega_dos_veces_el_mismo_trabajo():
    import os
    import threading

    from backend.storage.postgres import PostgresStore

    store = PostgresStore(os.environ["CYC_TEST_DATABASE_URL"], max_size=6)
    try:
        with store.pool.connection() as conn:
            conn.execute("TRUNCATE verifier_jobs, verifier_sources")
        q = cola.PgQueue(store.pool)
        ids = {q.enqueue("verify", "t1", {"n": i})["id"] for i in range(5)}
        got, lock = [], threading.Lock()

        def take():
            while (job := q.claim()) is not None:
                with lock:
                    got.append(job["id"])

        threads = [threading.Thread(target=take) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(got) == sorted(ids)  # cada trabajo una sola vez
        job = q.get(got[0])
        with pytest.raises(cola.LeaseError):
            q.finish(job["id"], "otro", "done", {})
        q.progress(job["id"], job["lease_id"], {"stage": "tests"})
        assert q.finish(job["id"], job["lease_id"], "done", {"ok": 1})["result"] == {"ok": 1}
        sid = q.put_source("t1", b"PK\x03\x04datos")
        assert q.get_source(sid) == b"PK\x03\x04datos"
    finally:
        store.close()


def test_ante_cuota_el_adaptador_espera_mas_y_no_gasta_los_reintentos(monkeypatch):
    import asyncio

    from backend import llm

    class Quota(Exception):
        code = 429

    calls, sleeps = {"n": 0}, []

    async def fake_call(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise Quota("429 RESOURCE_EXHAUSTED")
        return '{"ok": true}', 1, 1

    async def fake_sleep(s):
        sleeps.append(s)

    class Out(llm.BaseModel):
        ok: bool

    monkeypatch.setenv("LLM_JUEZ_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "falso")
    monkeypatch.setattr(llm, "_gemini_call", fake_call)
    monkeypatch.setattr(llm, "_gemini_transient", lambda exc: True)
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    out = asyncio.run(llm.structured("juez", "s", [], Out, gemini_client=object()))
    assert out.ok and calls["n"] == 4
    assert [round(s / b, 2) >= 0.75 for s, b in zip(sleeps, llm.QUOTA_BACKOFF_SECS)] == [True, True, True]
