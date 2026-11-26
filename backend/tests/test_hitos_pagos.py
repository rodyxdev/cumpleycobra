"""Evaluación, verificación por ejecución y pago por hito (etapa 2 de docs/hitos/diseno.md).

Todo sin red: contrato y modelo falsos, cubriendo `/evaluate`, `/tasks/{id}/verificaciones`,
guardias, 3 envíos por hito, caché independiente, orden secuencial, entrega, veredictos y
consentimiento por hito.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import gemini, main
from backend.ejecucion import cola, juez
from backend.ejecucion import suite as suite_mod
from backend.hashing import code_hash, verdict_hash_v2
from backend.plantilla import DEMO_SPEC
from backend.state import StateStore
from backend.stellar_client import ContractError, ReleaseOutcome, StellarUnavailable

CLIENT = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
FREELANCER = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
OTHER = "GA377V33S3W75F5R746764X27P7N27P7N27P7N27P7N27P7N27P7N27P"
CONTRACT_V3 = "CCBZZMNYLDIDL55G7LFGVPRA2QPVTPOGYKWDNO3GKQ2CHRIR5O5JFJTC"
NOW = 1_000_000
QUEUE_TOKEN = "token-cola-hitos-tests"
CASOS = Path(main.__file__).resolve().parent / "casos"

INTERFACE = {"language": "python", "symbols": [{
    "module": "descuentos", "name": "aplicar_descuento", "kind": "function",
    "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]",
    "description": "Devuelve cada precio con el descuento aplicado, redondeado a 2 decimales."}]}

CODE_OK_0 = "def aplicar_descuento(precios, porcentaje):\n    return [round(p * (1 - porcentaje / 100), 2) for p in precios]\n"
CODE_OK_1 = "def aplicar_descuento(precios, porcentaje):\n    factor = 1 - porcentaje / 100\n    return [round(p * factor, 2) for p in precios]\n"
CODE_BAD_1 = "def aplicar_descuento(precios, porcentaje):\n    return precios\n"
CODE_BAD_2 = "def aplicar_descuento(precios, porcentaje):\n    return [0 for _ in precios]\n"
CODE_BAD_3 = "def aplicar_descuento(precios, porcentaje):\n    return [p for p in precios]\n"
CODE_BAD_4 = "def aplicar_descuento(precios, porcentaje):\n    return []\n"

MILESTONES_IN = [
    {"title": "Hito 1: fórmula base", "criteria": ["Aplica el descuento", "Devuelve lista"], "amount": 4_000_000,
     "deadline_minutes": 60},
    {"title": "Hito 2: redondeo y bordes", "criteria": ["Redondea a 2 decimales", "Soporta lista vacía"],
     "amount": 6_000_000, "deadline_minutes": 120},
]


def llm_verdict(n_criteria: int, approved: bool = True, reason: str = "Cumple todos los criterios.") -> str:
    mark = "✓" if approved else "✗"
    return json.dumps({
        "trace": ["paso"],
        "logic": ["lógica"],
        "comparison": [f"{mark} Criterio {i}: {'sí' if approved else 'no'}" for i in range(1, n_criteria + 1)],
        "security_flags": [],
        "approved": approved,
        "reason": reason,
    })


class FakeMilestoneChain:
    def __init__(self, milestones_state: list[dict], release_fn=None):
        self.now = NOW
        self.milestones = [dict(m) for m in milestones_state]
        self.onchain_freelancer: str | None = None
        self.client = CLIENT
        self._release_fn = release_fn
        self.release_calls: list[tuple[str, int, str, str, str]] = []
        self.v1_release_calls = 0
        self.trustline = True
        self.failed_txs: set[str] = set()

    def has_usdc_trustline(self, address):
        return self.trustline

    def ledger_time(self):
        return self.now

    def transaction_succeeded(self, tx_hash):
        return tx_hash not in self.failed_txs

    def get_task(self, task_id):
        return None

    def get_project(self, task_id):
        return {
            "task_id": task_id,
            "client": self.client,
            "freelancer": self.onchain_freelancer,
            "total": sum(m["amount"] for m in self.milestones),
            "milestones": [dict(m) for m in self.milestones],
        }

    def release(self, task_id, freelancer, ch, vh, on_signed):
        self.v1_release_calls += 1
        raise AssertionError("Una tarea por hitos nunca debe llamar a release v1")

    def release_milestone(self, task_id, index, freelancer, ch, vh, on_signed):
        self.release_calls.append((task_id, index, freelancer, ch, vh))
        if self._release_fn is not None:
            return self._release_fn(self, index, on_signed)
        tx = f"{index + 1:02x}" * 32
        on_signed(tx)
        self.milestones[index]["status"] = "Released"
        self.onchain_freelancer = freelancer
        return ReleaseOutcome("success", tx)


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate_content(self, **_):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r})()


class FakeGemini:
    def __init__(self, responses):
        self.aio = type("A", (), {})()
        self.aio.models = FakeModels(responses)


def _sync_chain_from_created(created: dict, *, deadline_offset: int = 3600, release_fn=None) -> FakeMilestoneChain:
    state = [
        {
            "index": m["index"],
            "amount": m["amount"],
            "deadline": NOW + deadline_offset + m["index"] * 600,
            "rules_hash": m["rules_hash"],
            "status": "Funded",
        }
        for m in created["milestones"]
    ]
    return FakeMilestoneChain(state, release_fn=release_fn)


@pytest.fixture
def static_world(tmp_path, monkeypatch):
    monkeypatch.setenv("MILESTONES_ENABLED", "true")
    monkeypatch.setenv("MILESTONES_CONTRACT_ID", CONTRACT_V3)
    monkeypatch.setattr(gemini, "BACKOFF_SECS", (0, 0))

    def make(*, sequential: bool = False, responses=(), release_fn=None, deadline_offset: int = 3600):
        main.app.state.store = StateStore(tmp_path / "state.json")
        main.app.state.gemini = FakeGemini(responses or [llm_verdict(2), llm_verdict(2)])
        main.app.state.settings = type("S", (), {"gemini_model": "falso", "milestones_contract_id": CONTRACT_V3})()
        # Cadena provisional con trustline para poder crear y aceptar la tarea antes de poblar los hashes.
        temp_chain = FakeMilestoneChain([], release_fn=release_fn)
        main.app.state.chain = temp_chain
        client = TestClient(main.app)
        body = {
            "client_address": CLIENT,
            **DEMO_SPEC,
            "amount": 10_000_000,
            "deadline_minutes": 120,
            "milestones": MILESTONES_IN,
            "sequential": sequential,
        }
        r = client.post("/tasks", json=body)
        assert r.status_code == 200, r.text
        created = r.json()
        chain = _sync_chain_from_created(created, deadline_offset=deadline_offset, release_fn=release_fn)
        main.app.state.chain = chain
        ft = client.post(
            f"/tasks/{created['task_id']}/accept",
            json={"freelancer_address": FREELANCER, "invite_token": created["invite_token"]},
        ).json()["freelancer_token"]
        return client, chain, created, ft

    return make


# --- /evaluate por hito ------------------------------------------------------------------


def test_evaluate_guardias_de_hito(static_world):
    client, chain, created, ft = static_world()
    tid = created["task_id"]
    hdr = {"X-Freelancer-Token": ft}

    # Sin milestone en tarea por hitos -> 400
    r = client.post("/evaluate", headers=hdr, json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0})
    assert r.status_code == 400 and r.json()["error"] == "INVALID_REQUEST"

    # Índice fuera de rango -> 404 MILESTONE_NOT_FOUND
    r = client.post("/evaluate", headers=hdr,
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 2})
    assert r.status_code == 404 and r.json()["error"] == "MILESTONE_NOT_FOUND"

    # Token inválido siempre responde 403 antes de revisar el hito
    r = client.post("/evaluate", headers={"X-Freelancer-Token": "malo"},
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 99})
    assert r.status_code == 403 and r.json()["error"] == "INVALID_TOKEN"

    # Hito reembolsado -> 409 TASK_NOT_FUNDED
    chain.milestones[0]["status"] = "Refunded"
    r = client.post("/evaluate", headers=hdr,
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r.status_code == 409 and r.json()["error"] == "TASK_NOT_FUNDED"
    chain.milestones[0]["status"] = "Funded"

    # Monto o rules_hash distintos on-chain -> 409 TASK_MISMATCH
    orig_amount = chain.milestones[0]["amount"]
    chain.milestones[0]["amount"] = orig_amount + 1
    r = client.post("/evaluate", headers=hdr,
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r.status_code == 409 and r.json()["error"] == "TASK_MISMATCH"
    chain.milestones[0]["amount"] = orig_amount

    # Proyecto fijado a otro programador on-chain -> 409 TASK_MISMATCH
    chain.onchain_freelancer = OTHER
    r = client.post("/evaluate", headers=hdr,
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r.status_code == 409 and r.json()["error"] == "TASK_MISMATCH"
    chain.onchain_freelancer = None

    # Plazo menor al margen mínimo (120 s) -> 409 DEADLINE_TOO_CLOSE
    chain.milestones[0]["deadline"] = NOW + 60
    r = client.post("/evaluate", headers=hdr,
                    json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r.status_code == 409 and r.json()["error"] == "DEADLINE_TOO_CLOSE"

    # Tarea simple con milestone -> 400
    simple = client.post("/tasks", json={"client_address": CLIENT, **DEMO_SPEC, "amount": 5_000_000,
                                         "deadline_minutes": 30}).json()
    sft = client.post(f"/tasks/{simple['task_id']}/accept",
                      json={"freelancer_address": FREELANCER, "invite_token": simple["invite_token"]}).json()["freelancer_token"]
    r = client.post("/evaluate", headers={"X-Freelancer-Token": sft},
                    json={"task_id": simple["task_id"], "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r.status_code == 400 and r.json()["error"] == "INVALID_REQUEST"


def test_evaluate_paga_cada_hito_con_release_milestone(static_world):
    client, chain, created, ft = static_world()
    tid = created["task_id"]
    hdr = {"X-Freelancer-Token": ft}

    r0 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r0.status_code == 200, r0.text
    d0 = r0.json()
    assert d0["approved"] is True
    assert d0["milestone"] == 0
    assert d0["transaction_hash"] == "01" * 32
    assert d0["submissions_used"] == 1

    r1 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_1, "milestone": 1})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["approved"] is True
    assert d1["milestone"] == 1
    assert d1["transaction_hash"] == "02" * 32
    assert d1["submissions_used"] == 1

    assert chain.v1_release_calls == 0
    assert [(c[0], c[1], c[2], c[3]) for c in chain.release_calls] == [
        (tid, 0, FREELANCER, code_hash(CODE_OK_0)),
        (tid, 1, FREELANCER, code_hash(CODE_OK_1)),
    ]


def test_tres_envios_y_cache_independientes_por_hito(static_world):
    responses = [
        llm_verdict(2, approved=False, reason="Falla 1"),
        llm_verdict(2, approved=False, reason="Falla 2"),
        llm_verdict(2, approved=False, reason="Falla 3"),
        llm_verdict(2, approved=True, reason="Cumple en hito 2"),
    ]
    client, chain, created, ft = static_world(responses=responses)
    tid = created["task_id"]
    hdr = {"X-Freelancer-Token": ft}

    for i, code in enumerate((CODE_BAD_1, CODE_BAD_2, CODE_BAD_3), start=1):
        r = client.post("/evaluate", headers=hdr,
                        json={"task_id": tid, "freelancer_address": FREELANCER, "code": code, "milestone": 0})
        assert r.status_code == 200 and r.json()["approved"] is False
        assert r.json()["submissions_used"] == i and r.json()["milestone"] == 0

    # 4.º código distinto en el hito 0 -> 429 TOO_MANY_SUBMISSIONS
    r4 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_BAD_4, "milestone": 0})
    assert r4.status_code == 429 and r4.json()["error"] == "TOO_MANY_SUBMISSIONS"

    # Reenviar un código ya evaluado en el hito 0 responde desde su caché incluso con 3 envíos agotados
    rc = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_BAD_1, "milestone": 0})
    assert rc.status_code == 200 and rc.json()["stage"] == "cache"
    assert rc.json()["milestone"] == 0 and rc.json()["submissions_used"] == 3

    # El mismo código en el hito 1 NO usa la caché ni los envíos del hito 0
    rm1 = client.post("/evaluate", headers=hdr,
                      json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_BAD_1, "milestone": 1})
    assert rm1.status_code == 200
    d1 = rm1.json()
    assert d1["stage"] == "llm" and d1["approved"] is True
    assert d1["milestone"] == 1 and d1["submissions_used"] == 1
    assert d1["transaction_hash"] == "02" * 32
    assert len(chain.release_calls) == 1 and chain.release_calls[0][1] == 1


def test_orden_secuencial_bloquea_hito_siguiente_hasta_cobrar_anterior(static_world):
    client, chain, created, ft = static_world(sequential=True)
    tid = created["task_id"]
    hdr = {"X-Freelancer-Token": ft}

    # Hito 1 antes de cobrar el hito 0 -> 409 PREVIOUS_MILESTONE_NOT_RELEASED (no cuenta envío)
    blocked = client.post("/evaluate", headers=hdr,
                          json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_1, "milestone": 1})
    assert blocked.status_code == 409 and blocked.json()["error"] == "PREVIOUS_MILESTONE_NOT_RELEASED"
    assert main.app.state.store.tasks[tid]["milestones"][1]["submissions"] == []

    # Cobra el hito 0
    r0 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0})
    assert r0.status_code == 200 and r0.json()["transaction_hash"] == "01" * 32

    # Ahora el hito 1 sí puede evaluarse y cobrarse
    r1 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_1, "milestone": 1})
    assert r1.status_code == 200 and r1.json()["transaction_hash"] == "02" * 32


def test_reintento_de_pago_y_errores_de_contrato_por_hito(static_world):
    mode = {"m0": "net_fail", "m1": "deadline"}

    def release_fn(chain, index, on_signed):
        if index == 0:
            if mode["m0"] == "net_fail":
                raise StellarUnavailable("RPC temporalmente caído")
            if mode["m0"] == "not_funded_own":
                tx = "aa" * 32
                on_signed(tx)
                chain.milestones[0]["status"] = "Released"
                chain.onchain_freelancer = FREELANCER
                raise ContractError(6, "NotFunded")
            tx = "11" * 32
            on_signed(tx)
            chain.milestones[0]["status"] = "Released"
            chain.onchain_freelancer = FREELANCER
            return ReleaseOutcome("success", tx)
        raise ContractError(9, "DeadlinePassed")

    client, chain, created, ft = static_world(release_fn=release_fn)
    tid = created["task_id"]
    hdr = {"X-Freelancer-Token": ft}

    # Hito 0 falla por red -> queda retryable en caché del hito 0
    r0 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0}).json()
    assert r0["approved"] is True and r0["transaction_hash"] is None and r0["submissions_used"] == 1
    assert main.app.state.store.tasks[tid]["milestones"][0]["cache"][code_hash(CODE_OK_0)]["payment_retryable"] is True

    # Reenvío del mismo código reintenta el pago sin gastar otro envío; además prueba recuperación de #6
    mode["m0"] = "not_funded_own"
    r0_retry = client.post("/evaluate", headers=hdr,
                           json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_0, "milestone": 0}).json()
    assert r0_retry["stage"] == "cache" and r0_retry["transaction_hash"] == "aa" * 32
    assert r0_retry["submissions_used"] == 1 and r0_retry["milestone"] == 0

    # Hito 1 recibe #9 DeadlinePassed -> no es reintentable
    r1 = client.post("/evaluate", headers=hdr,
                     json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_1, "milestone": 1}).json()
    assert r1["approved"] is True and r1["transaction_hash"] is None
    assert "plazo" in r1["reason"].lower()
    assert main.app.state.store.tasks[tid]["milestones"][1]["cache"][code_hash(CODE_OK_1)]["payment_retryable"] is False


def test_delivery_verdicts_y_consent_por_hito(static_world):
    responses = [
        llm_verdict(2, approved=False, reason="Faltó validar entradas"),
        llm_verdict(2, approved=True, reason="Hito 2 impecable"),
    ]
    client, _chain, created, ft = static_world(responses=responses)
    tid = created["task_id"]
    ct = {"X-Client-Token": created["client_token"]}
    fh = {"X-Freelancer-Token": ft}

    # Hito 0 rechazado, hito 1 aprobado y pagado
    client.post("/evaluate", headers=fh,
                json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_BAD_1, "milestone": 0})
    client.post("/evaluate", headers=fh,
                json={"task_id": tid, "freelancer_address": FREELANCER, "code": CODE_OK_1, "milestone": 1})

    # Sin ?milestone -> 400
    assert client.get(f"/tasks/{tid}/delivery", headers=ct).status_code == 400
    assert client.get(f"/tasks/{tid}/verdicts", headers=ct).status_code == 400

    # Hito 1 pagado entrega su código; hito 0 sigue bloqueado
    d1 = client.get(f"/tasks/{tid}/delivery", params={"milestone": 1}, headers=ct)
    assert d1.status_code == 200 and d1.json()["code"] == CODE_OK_1 and d1.json()["milestone"] == 1
    d0_locked = client.get(f"/tasks/{tid}/delivery", params={"milestone": 0}, headers=ct)
    assert d0_locked.status_code == 409 and d0_locked.json()["error"] == "TASK_NOT_RELEASED"

    # Programador autoriza revisar la entrega rechazada del hito 0
    cs = client.post(f"/tasks/{tid}/consent", headers=fh, json={"milestone": 0})
    assert cs.status_code == 200 and cs.json()["consented"] is True and cs.json()["milestone"] == 0

    d0 = client.get(f"/tasks/{tid}/delivery", params={"milestone": 0}, headers=ct)
    assert d0.status_code == 200 and d0.json()["code"] == CODE_BAD_1 and d0.json()["milestone"] == 0

    # /verdicts separa cada hito
    v0 = client.get(f"/tasks/{tid}/verdicts", params={"milestone": 0}, headers=ct).json()
    v1 = client.get(f"/tasks/{tid}/verdicts", params={"milestone": 1}, headers=ct).json()
    assert v0["milestone"] == 0 and v0["submissions_used"] == 1 and v0["verdicts"][0]["consented"] is True
    assert v1["milestone"] == 1 and v1["submissions_used"] == 1 and v1["verdicts"][0]["transaction_hash"] == "02" * 32


# --- /tasks/{id}/verificaciones por hito (ejecución) -------------------------------------


HEADER = 'from cc_channel import remote\n\naplicar_descuento = remote("descuentos", "aplicar_descuento")\n\n'
EXEC_TESTS = {
    1: HEADER + 'def test_uno():\n    """Prueba criterio 1."""\n    assert aplicar_descuento([10.0], 0.0) == [10.0]\n',
    2: HEADER + 'def test_dos():\n    """Prueba criterio 2."""\n    assert aplicar_descuento([100.0], 10.0) == [90.0]\n',
}


def _run(outcomes):
    return {"report_found": True, "outcomes": outcomes, "stderr_tail": ""}


def _outcome(file, name, result):
    return {"nodeid": f"{file}::{name}", "file": file, "name": name, "outcome": result, "message": ""}


def _worker_headers():
    return {"Authorization": f"Bearer {QUEUE_TOKEN}"}


def _drive_one_suite(client):
    job = client.post("/verifier/claim", headers=_worker_headers()).json()
    assert job["kind"] == "suite"
    step = client.post(f"/verifier/jobs/{job['id']}/suite/generate", headers=_worker_headers(),
                       json={"lease_id": job["lease_id"]}).json()
    while step["next"] == "validate":
        outs = [_outcome(f, "test_x", "failed") for f in step["tests"]]
        ref = [_outcome(f, "test_x", "passed") for f in step["tests"]]
        step = client.post(
            f"/verifier/jobs/{job['id']}/suite/validation",
            headers=_worker_headers(),
            json={"lease_id": job["lease_id"], "empty": _run(outs), "stub": _run(outs),
                  "reference": _run(ref) if step.get("reference") else None},
        ).json()
    return job["payload"]["milestone"]


@pytest.fixture
def exec_world(tmp_path, monkeypatch):
    monkeypatch.setenv("MILESTONES_ENABLED", "true")
    monkeypatch.setenv("MILESTONES_CONTRACT_ID", CONTRACT_V3)
    monkeypatch.setenv("VERIFIER_ENABLED", "true")
    monkeypatch.setenv("VERIFIER_QUEUE_TOKEN", QUEUE_TOKEN)

    async def fake_structured(role, system, turns, output, **kw):
        if output is suite_mod.ReferenceImplementation:
            return suite_mod.ReferenceImplementation(modules=[suite_mod.ReferenceModule(
                module="descuentos", code=(CASOS / "a_feliz.py").read_text(encoding="utf-8"))])
        if role == "suite":
            index = json.loads(turns[0]["content"])["criterio_objetivo"]
            return suite_mod.GeneratedCriterion(tipo="test", motivo="se prueba llamando", plan=["un paso"],
                                                code=EXEC_TESTS[index])
        return juez.JudgeOutput(
            criteria=[juez.JudgeCriterion(numero=i, verdict="pass", reasoning="cumple", evidence=[]) for i in (1, 2)],
            injection_detected=False, injection_evidence=[], cheating_detected=False, cheating_evidence=[],
            summary="todo bien",
        )

    monkeypatch.setattr(suite_mod, "structured", fake_structured)
    monkeypatch.setattr(juez, "structured", fake_structured)

    def make(*, sequential: bool = False):
        main.app.state.store = StateStore(tmp_path / f"state_{sequential}.json")
        main.app.state.queue = cola.MemoryQueue()
        main.app.state.chain = FakeMilestoneChain([])
        main.app.state.gemini = object()
        main.app.state.settings = type("S", (), {"gemini_model": "falso", "milestones_contract_id": CONTRACT_V3})()
        client = TestClient(main.app)
        body = {
            "client_address": CLIENT,
            **DEMO_SPEC,
            "amount": 10_000_000,
            "deadline_minutes": 120,
            "verification": "execution",
            "interface": INTERFACE,
            "milestones": MILESTONES_IN,
            "sequential": sequential,
        }
        r = client.post("/tasks", json=body)
        assert r.status_code == 200, r.text
        created = r.json()
        chain = _sync_chain_from_created(created, deadline_offset=3600)
        main.app.state.chain = chain
        # Prepara las suites de ambos hitos
        prepared = {_drive_one_suite(client), _drive_one_suite(client)}
        assert prepared == {0, 1}
        ft = client.post(
            f"/tasks/{created['task_id']}/accept",
            json={"freelancer_address": FREELANCER, "invite_token": created["invite_token"]},
        ).json()["freelancer_token"]
        return client, chain, created, ft

    return make


def test_verificaciones_por_ejecucion_por_hito_guardias_y_pago(exec_world):
    client, chain, created, ft = exec_world(sequential=True)
    tid = created["task_id"]
    fh = {"X-Freelancer-Token": ft}
    src = {"kind": "code", "code": (CASOS / "a_feliz.py").read_text(encoding="utf-8")}

    # Guardias: sin milestone -> 400; fuera de rango -> 404; secuencial -> 409
    r_missing = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                            json={"freelancer_address": FREELANCER, "source": src})
    assert r_missing.status_code == 400 and r_missing.json()["error"] == "INVALID_REQUEST"

    r_oob = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                        json={"freelancer_address": FREELANCER, "source": src, "milestone": 5})
    assert r_oob.status_code == 404 and r_oob.json()["error"] == "MILESTONE_NOT_FOUND"

    r_seq = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                        json={"freelancer_address": FREELANCER, "source": src, "milestone": 1})
    assert r_seq.status_code == 409 and r_seq.json()["error"] == "PREVIOUS_MILESTONE_NOT_RELEASED"

    # Plazo menor a 300 s -> 409 DEADLINE_TOO_CLOSE
    orig_dl = chain.milestones[0]["deadline"]
    chain.milestones[0]["deadline"] = NOW + 120
    r_dl = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                       json={"freelancer_address": FREELANCER, "source": src, "milestone": 0})
    assert r_dl.status_code == 409 and r_dl.json()["error"] == "DEADLINE_TOO_CLOSE"
    chain.milestones[0]["deadline"] = orig_dl

    # Encola hito 0 y bloquea un segundo envío simultáneo del mismo hito
    enq0 = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                       json={"freelancer_address": FREELANCER, "source": src, "milestone": 0})
    assert enq0.status_code == 202 and enq0.json()["milestone"] == 0 and enq0.json()["submissions_used"] == 0
    vid0 = enq0.json()["verification_id"]
    dup0 = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                       json={"freelancer_address": FREELANCER, "source": src, "milestone": 0})
    assert dup0.status_code == 409 and dup0.json()["error"] == "VERIFICATION_IN_PROGRESS"

    # El trabajador reclama el trabajo del hito 0 y entrega evidencia aprobatoria
    job0 = client.post("/verifier/claim", headers=_worker_headers()).json()
    assert job0["id"] == vid0 and job0["payload"]["milestone"] == 0
    assert set(job0["payload"]["tests"]) == {"test_c1.py", "test_c2.py"}
    ev0 = {
        "workspace_hash": "sha256:" + "a0" * 32,
        "files": {"descuentos.py": src["code"]},
        "hygiene": {"blockers": [], "warnings": [], "requirements": []},
        "build": None,
        "tests": {"report_found": True, "timed_out": False,
                  "outcomes": [_outcome("test_c1.py", "test_uno", "passed"),
                               _outcome("test_c2.py", "test_dos", "passed")]},
    }
    res0 = client.post(f"/verifier/jobs/{vid0}/result", headers=_worker_headers(),
                       json={"lease_id": job0["lease_id"], "evidence": ev0})
    assert res0.status_code == 200

    st0 = client.get(f"/verificaciones/{vid0}", headers=fh).json()
    assert st0["status"] == "done" and st0["milestone"] == 0 and st0["submissions_used"] == 1
    assert st0["result"]["approved"] is True and st0["result"]["milestone"] == 0
    assert st0["result"]["transaction_hash"] == "01" * 32
    expected_vh0 = verdict_hash_v2(
        task_id=tid,
        rules_hash=created["milestones"][0]["rules_hash"],
        suite_hash=main.app.state.store.tasks[tid]["milestones"][0]["suite"]["suite_hash"],
        workspace_hash="sha256:" + "a0" * 32,
        approved=True,
        stage="final",
        criteria=[{"index": 1, "status": "pass"}, {"index": 2, "status": "pass"}],
        video_url=None,
    )
    assert st0["result"]["verdict_hash"] == expected_vh0
    assert chain.release_calls == [(tid, 0, FREELANCER, "a0" * 32, expected_vh0)]

    # Con hito 0 pagado, el hito 1 ya se desbloquea y cobra por separado
    enq1 = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                       json={"freelancer_address": FREELANCER, "source": src, "milestone": 1})
    assert enq1.status_code == 202 and enq1.json()["milestone"] == 1
    vid1 = enq1.json()["verification_id"]
    job1 = client.post("/verifier/claim", headers=_worker_headers()).json()
    assert job1["id"] == vid1 and job1["payload"]["milestone"] == 1
    ev1 = {**ev0, "workspace_hash": "sha256:" + "b1" * 32}
    assert client.post(f"/verifier/jobs/{vid1}/result", headers=_worker_headers(),
                       json={"lease_id": job1["lease_id"], "evidence": ev1}).status_code == 200
    st1 = client.get(f"/verificaciones/{vid1}", headers=fh).json()
    assert st1["status"] == "done" and st1["milestone"] == 1 and st1["submissions_used"] == 1
    assert st1["result"]["transaction_hash"] == "02" * 32
    assert len(chain.release_calls) == 2 and chain.release_calls[1][1] == 1
    # El hash del hito 1 difiere del hito 0 porque usa rules_hash v3 del hito 1
    assert st1["result"]["verdict_hash"] != st0["result"]["verdict_hash"]


def test_verificaciones_en_paralelo_y_envios_por_hito(exec_world):
    client, _chain, created, ft = exec_world(sequential=False)
    tid = created["task_id"]
    fh = {"X-Freelancer-Token": ft}
    src = {"kind": "code", "code": (CASOS / "a_feliz.py").read_text(encoding="utf-8")}

    # Sin orden secuencial, hito 0 e hito 1 pueden tener verificaciones en curso a la vez
    r0 = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                     json={"freelancer_address": FREELANCER, "source": src, "milestone": 0})
    r1 = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                     json={"freelancer_address": FREELANCER, "source": src, "milestone": 1})
    assert r0.status_code == 202 and r1.status_code == 202

    # Si el hito 0 agota sus 3 envíos, el hito 1 todavía puede encolar
    task = main.app.state.store.tasks[tid]
    task["milestones"][0]["submissions"] = [{"code_hash": f"{i}" * 64} for i in range(3)]
    # Reinicia la cola para dejar sin verificaciones en curso
    main.app.state.queue = cola.MemoryQueue()
    r0_full = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                          json={"freelancer_address": FREELANCER, "source": src, "milestone": 0})
    r1_ok = client.post(f"/tasks/{tid}/verificaciones", headers=fh,
                        json={"freelancer_address": FREELANCER, "source": src, "milestone": 1})
    assert r0_full.status_code == 429 and r0_full.json()["error"] == "TOO_MANY_SUBMISSIONS"
    assert r1_ok.status_code == 202 and r1_ok.json()["submissions_used"] == 0
