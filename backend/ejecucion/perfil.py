"""Lo que cambia entre el perfil script (funciones de Python) y el perfil web (sitio en un navegador)."""

from __future__ import annotations

from verifier.contract import ExecutionSpec

from . import suite as suite_mod
from . import web as web_mod


def is_web(spec: dict) -> bool:
    return spec.get("web") is not None


def execution_spec(spec: dict) -> dict:
    """Lo mínimo que necesita el verificador para ejecutar una entrega de la tarea."""
    if is_web(spec):
        built = ExecutionSpec(profile="web", web=spec["web"], allowed_dependencies=spec["allowed_deps"])
    else:
        built = ExecutionSpec(profile="script", interface=spec["interface"], allowed_dependencies=spec["allowed_deps"])
    return built.model_dump(mode="json", exclude_none=True)


def suite_module(suite: dict):
    return web_mod if suite.get("profile") == "web" else suite_mod


def public_plan(suite: dict | None) -> dict | None:
    if not suite:
        return None
    return suite_module(suite).public_plan(suite)
