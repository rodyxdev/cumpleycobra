"""Adaptador (lado NO confiable): atiende UNA llamada y termina.

Lee de stdin `{"module", "name", "args", "kwargs"}`, importa la entrega, llama a la
función y escribe una línea JSON con el resultado en el descriptor de protocolo. Lo que la
entrega imprima va a stderr, para que no se mezcle con el protocolo.
"""

import importlib
import json
import os
import sys
import traceback

PROTO = os.fdopen(os.dup(1), "w", encoding="utf-8")
os.dup2(2, 1)  # print() de la entrega → stderr

sys.path.insert(0, "/cc")
import cc_codec  # noqa: E402

for _path in ("/workspace", "/deps"):
    if _path not in sys.path:
        sys.path.append(_path)


def respond(payload):
    for stream in (sys.stdout, sys.stderr):  # lo que imprimió la entrega queda como evidencia
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 - la entrega pudo haber cerrado o reemplazado el stream
            pass
    PROTO.write(json.dumps(payload, ensure_ascii=False) + "\n")
    PROTO.flush()
    os._exit(0)  # sin atexit ni finalizadores de la entrega


def tail(text, n=2000):
    return text[-n:]


def main():
    request = json.loads(sys.stdin.read())
    try:
        module = importlib.import_module(request["module"])
    except BaseException:  # noqa: BLE001 - incluye SystemExit al importar
        respond({"status": "import_error", "message": tail(traceback.format_exc())})
    target = getattr(module, request["name"], None)
    if not callable(target):
        respond({"status": "missing", "message": f"{request['module']}.{request['name']} no existe o no es invocable"})
    try:
        args = cc_codec.decode(request.get("args", []))
        kwargs = cc_codec.decode(request.get("kwargs", {}))
        value = target(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001
        respond({
            "status": "raised",
            "type": type(exc).__name__,
            "module": type(exc).__module__,
            "message": str(exc)[:4000],
            "traceback": tail(traceback.format_exc()),
        })
    try:
        encoded = cc_codec.encode(value)
    except (TypeError, ValueError):
        encoded = {"$repr": repr(value)[:2000], "$type": type(value).__name__}
    respond({"status": "ok", "value": encoded})


main()
