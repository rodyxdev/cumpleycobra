"""Verifica un pago: recalcula verdict_hash (y code_hash) y los compara con el evento release.

Uso:
  backend/.venv/Scripts/python scripts/verificar_pago.py TX_HASH --veredicto veredicto.json [--codigo entrega.py] [--tarea TASK_ID]

  veredicto.json puede ser:
    - la respuesta de POST /evaluate;
    - la respuesta completa de GET /tasks/{id}/verdicts (se toma el veredicto cuyo code_hash es el del evento);
    - un solo elemento de GET /tasks/{id}/verdicts (entonces el task_id va en --tarea).
  entrega.py: el código tal como lo entregó el programador (GET /tasks/{id}/delivery, extraído con jq -j .code).

Lee la transacción del RPC de testnet; no necesita el backend ni llaves. Código de salida 1 si algo
no coincide.
"""
import argparse
import json
import sys
from pathlib import Path

from stellar_sdk import SorobanServer, StrKey, scval, xdr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.hashing import code_hash, verdict_hash  # noqa: E402

RPC = "https://soroban-testnet.stellar.org"
CONTRACT_ID = "CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"


def release_event(tx_hash: str) -> dict:
    tx = SorobanServer(RPC).get_transaction(tx_hash)
    if tx.status.value != "SUCCESS" or not tx.events:
        raise SystemExit(f"La transacción no está en el RPC o no fue exitosa (estado {tx.status.value}).")
    for group in tx.events.contract_events_xdr or []:
        for b64 in group:
            event = xdr.ContractEvent.from_xdr(b64)
            if not event.contract_id or StrKey.encode_contract(event.contract_id.contract_id.hash) != CONTRACT_ID:
                continue
            topics = [scval.to_native(t) for t in event.body.v0.topics]
            if topics and topics[0] == "release":
                data = scval.to_native(event.body.v0.data)
                return {"task_id": topics[1], "freelancer": data["freelancer"].address, "amount": data["amount"],
                        "code_hash": data["code_hash"].hex(), "verdict_hash": data["verdict_hash"].hex()}
    raise SystemExit("La transacción no tiene un evento release del contrato de Cumple&Cobra.")


def select_verdict(data: dict, event_code_hash: str, task_id: str | None = None) -> tuple[dict, str, list[str]]:
    """Normaliza la entrada a (veredicto, task_id, notas), venga de /evaluate o de /verdicts."""
    notes = []
    if "verdicts" in data:
        task_id = data["task_id"]
        matches = [v for v in data["verdicts"] if v["code_hash"] == event_code_hash]
        if not matches:
            raise SystemExit("La respuesta de /verdicts no tiene un veredicto con el code_hash del evento.")
        verdict = matches[0]
        notes.append("veredicto tomado de la respuesta de /verdicts")
    else:
        verdict = data
        task_id = data.get("task_id") or task_id
        if not task_id:
            raise SystemExit("Falta el task_id: un elemento suelto de /verdicts no lo trae; usa --tarea.")
    if verdict["stage"] == "cache":
        # Un veredicto pagado siempre viene de Gemini: la capa determinista solo rechaza.
        verdict = {**verdict, "stage": "llm"}
        notes.append("respuesta de caché: se usa stage «llm», el del análisis original")
    return verdict, task_id, notes


def recompute_verdict_hash(verdict: dict, task_id: str) -> str:
    # En un veredicto pagado security_flags es [] (una bandera impide el pago); /verdicts no lo trae.
    return verdict_hash(task_id=task_id, code_hash=verdict["code_hash"], approved=verdict["approved"],
                        reason=verdict["reason"], stage=verdict["stage"], comparison=verdict["comparison"],
                        security_flags=verdict.get("security_flags", []), video_url=verdict.get("video_url"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tx_hash")
    parser.add_argument("--veredicto", required=True, type=Path)
    parser.add_argument("--codigo", type=Path)
    parser.add_argument("--tarea", help="task_id, si veredicto.json es un elemento suelto de /verdicts")
    args = parser.parse_args()

    event = release_event(args.tx_hash)
    data = json.loads(args.veredicto.read_text(encoding="utf-8"))
    verdict, task_id, notes = select_verdict(data, event["code_hash"], args.tarea)
    print(f"Evento release: tarea {event['task_id']}, {event['amount']} unidades a {event['freelancer']}")
    for note in notes:
        print(f"  ({note})")
    print(f"  code_hash    on-chain  {event['code_hash']}")
    print(f"  verdict_hash on-chain  {event['verdict_hash']}")

    checks = [("task_id", task_id == event["task_id"])]
    if args.codigo:
        # Bytes exactos, sin normalizar saltos de línea: así se calculó al recibirlo.
        recomputed_code = code_hash(args.codigo.read_bytes().decode("utf-8"))
        print(f"  code_hash    recalculado {recomputed_code}")
        checks.append(("code_hash del código entregado", recomputed_code == event["code_hash"]))
    checks.append(("code_hash del veredicto", verdict["code_hash"] == event["code_hash"]))
    recomputed = recompute_verdict_hash(verdict, task_id)
    print(f"  verdict_hash recalculado {recomputed}")
    checks.append(("verdict_hash", recomputed == event["verdict_hash"]))

    for label, ok in checks:
        print(f"{'✓' if ok else '✗'} {label}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
