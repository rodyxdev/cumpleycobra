"""Lo mínimo del acuerdo que necesita el verificador para ejecutar una entrega.

El acuerdo completo (descripción, criterios, ejemplos) vive en la API; aquí solo llega cómo
se ejecuta: el perfil, la interfaz (qué símbolos expone la entrega) y las dependencias permitidas.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Profile = Literal["script", "api"]
SymbolKind = Literal["function", "class", "asgi_app"]

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterfaceSymbol(_Strict):
    module: str = Field(pattern=_MODULE_RE.pattern, max_length=100,
                        description="Módulo con puntos, relativo a la raíz de la entrega (p. ej. 'descuentos')")
    name: str = Field(pattern=_NAME_RE.pattern, max_length=100)
    kind: SymbolKind
    signature: str = Field(max_length=300)
    description: str = Field(default="", max_length=500)


class Interface(_Strict):
    language: Literal["python"] = "python"
    symbols: list[InterfaceSymbol] = Field(min_length=1, max_length=20)


class ExecutionSpec(_Strict):
    """Cómo se ejecuta una entrega: perfil, interfaz y dependencias que puede declarar."""

    profile: Profile = "script"
    interface: Interface
    allowed_dependencies: list[str] = Field(default_factory=list, max_length=10)


def normalize_dist_name(name: str) -> str:
    """Nombre de distribución normalizado (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()
