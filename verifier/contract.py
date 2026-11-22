"""Lo mínimo del acuerdo que necesita el verificador para ejecutar una entrega.

El acuerdo completo (descripción, criterios, ejemplos) vive en la API; aquí solo llega cómo
se ejecuta: el perfil, la interfaz (qué símbolos expone la entrega) o las páginas (perfil web) y
las dependencias permitidas (PyPI, o npm en el perfil web).

Perfil web: los criterios que se ven en un navegador se comprueban con chequeos deterministas de un
catálogo fijo (`WebCheck`), que corre Playwright del lado confiable. Lo visual lo juzga el modelo
en la API con las capturas.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Profile = Literal["script", "api", "web"]
SymbolKind = Literal["function", "class", "asgi_app"]

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PAGE_RE = re.compile(r"^/[A-Za-z0-9._~/-]{0,100}$")

WebCheckKind = Literal[
    "text_present",            # args: [texto]               — visible en escritorio y en móvil
    "title_contains",          # args: [texto]               — <title> de la página
    "element_visible",         # args: [rol, nombre]         — p. ej. ["button", "Enviar"], en ambos anchos
    "link_navigates",          # args: [nombre, destino]     — destino "#ancla", "/ruta" o URL
    "form_submits",            # args: [endpoint, confirmación, "Etiqueta=valor", ..., "boton=Nombre"]
    "no_horizontal_overflow",  # args: []                    — a 390 px no hay scroll horizontal
]
# Cuántos argumentos lleva cada chequeo: (mínimo, máximo).
WEB_CHECK_ARGS = {"text_present": (1, 1), "title_contains": (1, 1), "element_visible": (2, 2),
                  "link_navigates": (2, 2), "form_submits": (3, 10), "no_horizontal_overflow": (0, 0)}
ARIA_ROLES = {"button", "link", "heading", "img", "textbox", "checkbox", "radio", "combobox", "navigation",
              "list", "listitem", "table", "form", "banner", "contentinfo", "main", "region", "dialog", "tab"}


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


class WebSpec(_Strict):
    pages: list[str] = Field(min_length=1, max_length=5, description="Rutas a revisar, p. ej. ['/']")

    @model_validator(mode="after")
    def _pages(self) -> "WebSpec":
        for page in self.pages:
            if not PAGE_RE.fullmatch(page) or ".." in page:
                raise ValueError(f"ruta de página inválida: {page!r} (debe empezar con / y sin ..)")
        if len(set(self.pages)) != len(self.pages):
            raise ValueError("páginas repetidas")
        return self


class WebCheck(_Strict):
    """Un chequeo determinista del catálogo, en una página."""

    id: str = Field(pattern=r"^c[0-9]{1,2}-[0-9]{1,2}$", description="c<criterio>-<n>")
    kind: WebCheckKind
    page: str = Field(max_length=101)
    args: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def _args(self) -> "WebCheck":
        low, high = WEB_CHECK_ARGS[self.kind]
        if not low <= len(self.args) <= high:
            raise ValueError(f"{self.kind} lleva entre {low} y {high} argumentos")
        if any(len(a) > 200 or not a.strip() for a in self.args):
            raise ValueError("cada argumento: texto no vacío de máximo 200 caracteres")
        if self.kind == "element_visible" and self.args[0] not in ARIA_ROLES:
            raise ValueError(f"rol ARIA no soportado: {self.args[0]!r}")
        if self.kind == "form_submits":
            if not self.args[0].startswith("/"):
                raise ValueError("form_submits: el endpoint empieza con /")
            fields = self.args[2:]
            if sum(a.startswith("boton=") for a in fields) != 1:
                raise ValueError('form_submits: exactamente un argumento "boton=Nombre"')
            if any("=" not in a for a in fields):
                raise ValueError('form_submits: los campos van como "Etiqueta=valor"')
        return self


class ExecutionSpec(_Strict):
    """Cómo se ejecuta una entrega: perfil, interfaz (o páginas) y dependencias que puede declarar."""

    profile: Profile = "script"
    interface: Interface | None = None
    web: WebSpec | None = None
    allowed_dependencies: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _profile(self) -> "ExecutionSpec":
        if self.profile == "web":
            if self.web is None or self.interface is not None:
                raise ValueError("el perfil web lleva páginas (web) y no interfaz")
        elif self.interface is None or self.web is not None:
            raise ValueError(f"el perfil {self.profile} lleva interfaz y no páginas")
        return self


def normalize_dist_name(name: str) -> str:
    """Nombre de distribución normalizado (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()
