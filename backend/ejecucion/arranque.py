"""Encendido de la VM del verificador cuando hay trabajo (fase 3).

La VM se apaga sola tras `VERIFIER_IDLE_SHUTDOWN_SECS` sin trabajos (ver `verifier/worker.py`).
La API la enciende:
- al encolar un trabajo (suite de una tarea nueva o una verificación), y
- cuando alguien consulta un trabajo que sigue en cola (la pantalla consulta cada pocos segundos),
  lo que cubre la carrera de un trabajo encolado justo mientras la VM se apagaba y las VMs Spot
  que Google detuvo.

Variables (sin `VERIFIER_VM_NAME` no hace nada; en local el trabajador corre a mano):
    VERIFIER_VM_NAME       nombre de la instancia (p. ej. cyc-verificador)
    VERIFIER_VM_ZONE       zona (por defecto us-central1-a)
    VERIFIER_VM_PROJECT    proyecto (por defecto GOOGLE_CLOUD_PROJECT)

Permiso: la cuenta de servicio de la API recibe un rol personalizado con solo
`compute.instances.get` y `compute.instances.start`, y solo sobre esa instancia (ver
`verifier/deploy/deploy.ps1 -Arranque`). No puede detenerla, borrarla ni cambiarle nada.

Nunca bloquea la petición ni la hace fallar: corre en segundo plano y solo deja registro.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

log = logging.getLogger("cumpleycobra.arranque")

COMPUTE = "https://compute.googleapis.com/compute/v1"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MIN_INTERVAL_SECS = 30          # entre dos revisiones del estado de la VM
STOPPING_RECHECK_SECS = 5       # si se estaba apagando, se revisa antes
STOPPED = ("TERMINATED", "STOPPED")


class VmStarter:
    def __init__(self, project: str, zone: str, name: str, *, credentials=None,
                 transport: httpx.AsyncBaseTransport | None = None, clock=time.monotonic):
        self.project, self.zone, self.name = project, zone, name
        self.url = f"{COMPUTE}/projects/{project}/zones/{zone}/instances/{name}"
        self._credentials, self._transport, self._clock = credentials, transport, clock
        self._last_check: float | None = None
        self._task: asyncio.Task | None = None
        self.last_status: str | None = None

    async def _token(self) -> str:
        from starlette.concurrency import run_in_threadpool

        if self._credentials is None:
            import google.auth

            self._credentials, _ = await run_in_threadpool(google.auth.default, scopes=[SCOPE])
        if not self._credentials.valid:
            from google.auth.transport.requests import Request

            await run_in_threadpool(self._credentials.refresh, Request())
        return self._credentials.token

    async def check_and_start(self) -> str | None:
        """Lee el estado de la VM y, si está detenida, la enciende. Devuelve el estado visto."""
        try:
            headers = {"Authorization": f"Bearer {await self._token()}"}
            async with httpx.AsyncClient(timeout=15, transport=self._transport) as http:
                resp = await http.get(self.url, headers=headers)
                resp.raise_for_status()
                status = resp.json().get("status")
                self.last_status = status
                if status in STOPPED:
                    start = await http.post(f"{self.url}/start", headers=headers)
                    start.raise_for_status()
                    log.info("VM del verificador %s estaba %s: se pidió encenderla", self.name, status)
                    self.last_status = "STARTING"
                elif status == "STOPPING":
                    # Se está apagando (inactividad o Spot): no se puede encender todavía. La siguiente
                    # consulta vuelve a revisar en STOPPING_RECHECK_SECS y entonces la enciende.
                    self._last_check = self._clock() - MIN_INTERVAL_SECS + STOPPING_RECHECK_SECS
                return self.last_status
        except Exception as exc:  # noqa: BLE001 - nunca rompe la petición que la disparó
            log.warning("no se pudo revisar o encender la VM del verificador (%s: %s)",
                        type(exc).__name__, str(exc)[:200])
            return None

    def poke(self) -> None:
        """Revisa la VM en segundo plano, como mucho una vez cada MIN_INTERVAL_SECS."""
        now = self._clock()
        if self._last_check is not None and now - self._last_check < MIN_INTERVAL_SECS:
            return
        if self._task is not None and not self._task.done():
            return
        self._last_check = now
        try:
            self._task = asyncio.get_running_loop().create_task(self.check_and_start())
        except RuntimeError:  # sin event loop (scripts): no hay a quién avisar
            self._task = None


def make_starter() -> VmStarter | None:
    name = (os.environ.get("VERIFIER_VM_NAME") or "").strip()
    if not name:
        return None
    project = (os.environ.get("VERIFIER_VM_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        log.warning("VERIFIER_VM_NAME sin proyecto (VERIFIER_VM_PROJECT o GOOGLE_CLOUD_PROJECT): no se encenderá la VM")
        return None
    zone = (os.environ.get("VERIFIER_VM_ZONE") or "us-central1-a").strip()
    return VmStarter(project, zone, name)


def wake(app) -> None:
    """Pide revisar la VM si la API tiene configurado el encendido (no-op si no)."""
    starter = getattr(app.state, "vm_starter", None)
    if starter is not None:
        starter.poke()


def suite_waiting(suite: dict | None) -> bool:
    return bool(suite) and suite.get("status") in ("pendiente", "validando")
