"""Workspace stub: los símbolos de la interfaz existen pero no hacen nada.

Una suite válida debe fallar TODOS sus tests contra el stub y contra una entrega vacía; si algo
pasa, ese test no comprueba el comportamiento acordado (v2, `verification/suite.py`).
"""

from __future__ import annotations

from pathlib import Path

from verifier.contract import Interface


def build_stub(interface: Interface, dest: Path) -> None:
    for sym in interface.symbols:
        parts = sym.module.split(".")
        pkg = dest
        for part in parts[:-1]:
            pkg = pkg / part
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "__init__.py").touch()
        module_file = pkg / f"{parts[-1]}.py"
        with module_file.open("a", encoding="utf-8", newline="\n") as fh:
            if sym.kind == "function":
                fh.write(f"\ndef {sym.name}(*args, **kwargs):\n    return None\n")
            elif sym.kind == "class":
                fh.write(
                    f"\nclass {sym.name}:\n"
                    "    def __init__(self, *args, **kwargs):\n        pass\n\n"
                    "    def __getattr__(self, name):\n        return lambda *a, **k: None\n"
                )
            elif sym.kind == "asgi_app":
                fh.write(
                    f"\nasync def {sym.name}(scope, receive, send):\n"
                    "    if scope['type'] == 'lifespan':\n"
                    "        while True:\n"
                    "            message = await receive()\n"
                    "            if message['type'] == 'lifespan.startup':\n"
                    "                await send({'type': 'lifespan.startup.complete'})\n"
                    "            elif message['type'] == 'lifespan.shutdown':\n"
                    "                await send({'type': 'lifespan.shutdown.complete'})\n"
                    "                return\n"
                    "    await send({'type': 'http.response.start', 'status': 501, 'headers': []})\n"
                    "    await send({'type': 'http.response.body', 'body': b''})\n"
                )
