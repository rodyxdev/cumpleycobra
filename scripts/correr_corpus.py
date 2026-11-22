"""Corre el corpus del verificador por ejecución (scripts/corpus_verificador) con el modelo real.

Todo en este proceso: la API (FastAPI con TestClient), la cola en memoria, el trabajador real del
verificador contra Docker local y un contrato falso (no toca testnet). El modelo es el configurado
por rol (`LLM_SUITE_PROVIDER`, `LLM_JUEZ_PROVIDER`; Gemini por Vertex por defecto, con backend/.env).

Por cada acuerdo: crea la tarea, genera y valida la suite oculta, y verifica cada entrega como un
ZIP (así sirven las de varios archivos). Escribe un JSON por corrida y un resumen.

Uso:
    backend/.venv/Scripts/python scripts/correr_corpus.py --corrida 1
    backend/.venv/Scripts/python scripts/correr_corpus.py --corrida prueba --tareas fizzbuzz --entregas correcta memoriza-ejemplo

Métrica que decide: 0 falsas aprobaciones (entrega que no debía aprobarse y se aprobó).
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(VERIFIER_ENABLED="true", VERIFIER_QUEUE_TOKEN="corpus-local")
os.environ.setdefault("CALL_TIMEOUT_S", "3")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from fastapi.testclient import TestClient  # noqa: E402

from backend import gemini, main  # noqa: E402
from backend.config import load_settings  # noqa: E402
from backend.ejecucion import cola  # noqa: E402
from backend.state import StateStore  # noqa: E402
from backend.stellar_client import ReleaseOutcome  # noqa: E402
from scripts.corpus_verificador import TAREAS  # noqa: E402
from verifier import worker  # noqa: E402

CLIENT = "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"
FREELANCER = "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"
AMOUNT = 10_000_000
WORKER_HEADERS = {"Authorization": "Bearer corpus-local"}


class FakeChain:
    """Contrato falso: la tarea siempre está Funded con el rules_hash de la tarea en curso."""

    def __init__(self):
        self.now, self.rules, self.status = 1_000_000, None, "Funded"
        self.releases = 0

    def has_usdc_trustline(self, address):
        return True

    def ledger_time(self):
        return self.now

    def transaction_succeeded(self, tx):
        return True

    def get_task(self, task_id):
        return {"task_id": task_id, "client": CLIENT, "amount": AMOUNT, "deadline": self.now + 7200,
                "rules_hash": self.rules, "status": self.status,
                "freelancer": FREELANCER if self.status == "Released" else None}

    def release(self, task_id, freelancer, ch, vh, on_signed):
        self.releases += 1
        on_signed("cc" * 32)
        self.status = "Released"
        return ReleaseOutcome("success", "cc" * 32)


class GeminiPorLoop:
    """Un cliente de Gemini por event loop: el TestClient abre un loop nuevo en cada petición."""

    def __init__(self, settings):
        self.settings, self.clients = settings, {}

    @property
    def aio(self):
        loop = id(asyncio.get_running_loop())
        if loop not in self.clients:
            self.clients[loop] = gemini.make_client(self.settings)
        return self.clients[loop].aio


def zip_b64(files: dict[str, str]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return base64.b64encode(buf.getvalue()).decode()


def run_worker(client: TestClient) -> None:
    """Atiende la cola hasta vaciarla (el trabajador real, hablando con la API por el TestClient)."""
    api = worker.Api("http://testserver", "corpus-local")
    api.http = client
    while True:
        client.headers.update(WORKER_HEADERS)
        raw = api.post("/verifier/claim", {})
        if raw is None:
            break
        worker.handle(worker.Job(api, raw))
    client.headers.pop("Authorization", None)


def main_corpus() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corrida", default="1")
    parser.add_argument("--tareas", nargs="*")
    parser.add_argument("--entregas", nargs="*")
    args = parser.parse_args()

    settings = load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="cyc-corpus-"))
    main.app.state.store = StateStore(tmp / "state.json")
    main.app.state.queue = cola.MemoryQueue()
    chain = FakeChain()
    main.app.state.chain = chain
    main.app.state.settings = settings
    main.app.state.gemini = GeminiPorLoop(settings)
    client = TestClient(main.app)

    salida = ROOT / "scripts" / ".logs" / f"corpus-{args.corrida}.json"
    salida.parent.mkdir(exist_ok=True)
    resultados: dict = {"corrida": args.corrida, "inicio": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "proveedor_suite": os.environ.get("LLM_SUITE_PROVIDER", "gemini"),
                        "proveedor_juez": os.environ.get("LLM_JUEZ_PROVIDER", "gemini"),
                        "modelo": settings.gemini_model, "tareas": []}

    for tarea in TAREAS:
        if args.tareas and tarea.NOMBRE not in args.tareas:
            continue
        t0 = time.monotonic()
        created = client.post("/tasks", json={"client_address": CLIENT, "raw_request": "", **tarea.ACUERDO,
                                              "amount": AMOUNT, "deadline_minutes": 120,
                                              "verification": "execution"}).json()
        tid = created["task_id"]
        chain.rules, chain.status = created["rules_hash"], "Funded"
        run_worker(client)
        task = main.app.state.store.tasks[tid]
        suite = task["suite"]
        info = {"tarea": tarea.NOMBRE, "task_id": tid, "suite_status": suite["status"], "suite_rondas": suite["round"],
                "suite_s": round(time.monotonic() - t0, 1),
                "suite_tipos": [c["tipo"] for c in suite["criteria"]],
                "suite_intentos": [c["attempts"] for c in suite["criteria"]],
                "suite_tokens": [sum(u["input_tokens"] for u in suite["usage"]), sum(u["output_tokens"] for u in suite["usage"])],
                "suite_problemas": {c["index"]: c["problems"][:1] for c in suite["criteria"] if c["problems"]},
                "entregas": []}
        print(f"[{args.corrida}] {tarea.NOMBRE}: suite {suite['status']} en {info['suite_s']} s, "
              f"{suite['round']} ronda(s), tipos {info['suite_tipos']}", flush=True)
        resultados["tareas"].append(info)
        if suite["status"] != "lista":
            continue
        ft = client.post(f"/tasks/{tid}/accept", json={"freelancer_address": FREELANCER,
                                                        "invite_token": created["invite_token"]}).json()["freelancer_token"]
        for entrega in tarea.ENTREGAS:
            if args.entregas and entrega["id"] not in args.entregas:
                continue
            task = main.app.state.store.tasks[tid]
            task["submissions"].clear()
            task["cache"].clear()
            task["release"] = None
            chain.status = "Funded"
            main.app.state.store.save()
            t1 = time.monotonic()
            r = client.post(f"/tasks/{tid}/verificaciones", headers={"X-Freelancer-Token": ft},
                            json={"freelancer_address": FREELANCER,
                                  "source": {"kind": "zip", "zip_b64": zip_b64(entrega["files"])}})
            fila = {"id": entrega["id"], "esperado": entrega["aprobar"], "motivo": entrega["motivo"]}
            if r.status_code != 202:
                fila.update(error=f"{r.status_code} {r.text[:200]}")
            else:
                run_worker(client)
                st = client.get(f"/verificaciones/{r.json()['verification_id']}",
                                headers={"X-Freelancer-Token": ft}).json()
                res = st.get("result") or {}
                ver = res.get("verification") or {}
                fila.update(
                    estado=st["status"], aprobado=res.get("approved"), etapa=res.get("stage"),
                    pagado=bool(res.get("transaction_hash")), segundos=round(time.monotonic() - t1, 1),
                    criterios=[c["status"] for c in ver.get("criteria", [])],
                    banderas=ver.get("flags"), razones=ver.get("reasons", [])[:3],
                    juez_tokens=[sum(u["input_tokens"] for u in ver.get("usage", [])),
                                 sum(u["output_tokens"] for u in ver.get("usage", []))],
                    error=st.get("error"))
            fila["falsa_aprobacion"] = bool(fila.get("aprobado")) and not entrega["aprobar"]
            fila["falso_rechazo"] = entrega["aprobar"] and not fila.get("aprobado")
            marca = "OK " if not (fila["falsa_aprobacion"] or fila["falso_rechazo"]) else "MAL"
            print(f"[{args.corrida}] {marca} {tarea.NOMBRE}/{entrega['id']}: esperado={entrega['aprobar']} "
                  f"obtenido={fila.get('aprobado')} etapa={fila.get('etapa')} {fila.get('segundos')} s "
                  f"{fila.get('error') or ''}", flush=True)
            info["entregas"].append(fila)
            salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")

    filas = [f for t in resultados["tareas"] for f in t["entregas"]]
    resultados["resumen"] = {
        "entregas": len(filas),
        "falsas_aprobaciones": [f"{t['tarea']}/{f['id']}" for t in resultados["tareas"] for f in t["entregas"] if f["falsa_aprobacion"]],
        "falsos_rechazos": [f"{t['tarea']}/{f['id']}" for t in resultados["tareas"] for f in t["entregas"] if f["falso_rechazo"]],
        "errores": [f"{t['tarea']}/{f['id']}" for t in resultados["tareas"] for f in t["entregas"] if f.get("error")],
        "suites_rechazadas": [t["tarea"] for t in resultados["tareas"] if t["suite_status"] != "lista"],
        "fin": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resultados["resumen"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main_corpus())
