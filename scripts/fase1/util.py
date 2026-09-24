"""Utilidades del script de la fase 1 (sin jq): armar cuerpos JSON y leer respuestas.

Uso:
  util.py get RUTA                      < json   -> imprime el valor (a.b.0.c)
  util.py task-body CLIENTE MONTO MINUTOS        -> cuerpo de POST /tasks (plantilla fija)
  util.py accept-body DIRECCION INVITACION
  util.py eval-body TASK_ID DIRECCION ARCHIVO [SUFIJO]
  util.py show                          < json   -> resumen legible (tokens abreviados)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TOKEN_KEYS = {"client_token", "invite_token", "freelancer_token"}


def get(path: str) -> None:
    data = json.load(sys.stdin)
    for part in path.split(".") if path else []:
        data = data[int(part)] if isinstance(data, list) else data.get(part)
        if data is None:
            break
    if data is None:
        print("null")
    elif isinstance(data, bool):
        print("true" if data else "false")
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(data)


def task_body(client: str, amount: str, minutes: str) -> None:
    from backend.plantilla import DEMO_RAW_REQUEST, DEMO_SPEC
    print(json.dumps({"client_address": client, "raw_request": DEMO_RAW_REQUEST, **DEMO_SPEC,
                      "amount": int(amount), "deadline_minutes": int(minutes)}, ensure_ascii=False))


def accept_body(address: str, invite: str) -> None:
    print(json.dumps({"freelancer_address": address, "invite_token": invite}))


def eval_body(task_id: str, address: str, file: str, suffix: str = "") -> None:
    code = Path(file).read_text(encoding="utf-8") + suffix
    print(json.dumps({"task_id": task_id, "freelancer_address": address, "code": code,
                      "video_url": None}, ensure_ascii=False))


def _redact(obj):
    if isinstance(obj, dict):
        return {k: (v[:6] + "…" if k in TOKEN_KEYS and isinstance(v, str) else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def show() -> None:
    data = _redact(json.load(sys.stdin))
    if "approved" in data:  # veredicto de /evaluate
        for key in ("approved", "stage", "transaction_hash", "submissions_used", "code_hash",
                    "verdict_hash"):
            if key in data:
                print(f"   {key}: {json.dumps(data[key], ensure_ascii=False)}")
        print(f"   reason: {data['reason']}")
        for flag in data.get("security_flags") or []:
            print(f"   security_flag: {flag}")
        for line in data.get("comparison") or []:
            print(f"   {line}")
    else:
        print("   " + json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    sys.stdout.reconfigure(encoding="utf-8")
    {"get": get, "task-body": task_body, "accept-body": accept_body,
     "eval-body": eval_body, "show": show}[cmd](*args)
