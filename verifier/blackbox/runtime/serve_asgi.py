"""Servidor (lado NO confiable, perfil api): levanta la app ASGI de la entrega en :8000."""

import importlib
import sys

for _path in ("/workspace", "/deps"):
    if _path not in sys.path:
        sys.path.append(_path)

import uvicorn  # noqa: E402  (viene de la imagen del SUT, no de la entrega)

module_name, _, attr = sys.argv[1].partition(":")
app = getattr(importlib.import_module(module_name), attr)
uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning", lifespan="auto")
