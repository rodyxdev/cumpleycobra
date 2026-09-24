"""Estado del backend: diccionario en memoria volcado a state.json en cada escritura.

No es una base de datos. El contrato es la fuente de verdad del dinero; aquí viven
las tareas, tokens, envíos, caché de veredictos, código entregado y hashes de release.
"""

import asyncio
import json
import os
from pathlib import Path


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"version": 1, "tasks": {}}
        self._locks: dict[str, asyncio.Lock] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                self.data = json.load(f)
        self.data.setdefault("tasks", {})

    @property
    def tasks(self) -> dict:
        return self.data["tasks"]

    def lock(self, task_id: str) -> asyncio.Lock:
        """Un asyncio.Lock por task_id: envíos y escrituras sin carreras."""
        if task_id not in self._locks:
            self._locks[task_id] = asyncio.Lock()
        return self._locks[task_id]

    def save(self) -> None:
        """Escritura atómica: archivo temporal y luego os.replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
