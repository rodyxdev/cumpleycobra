"""Tipos comunes de la capa de entrada."""

from __future__ import annotations

import os
import shutil
import sys
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal, Protocol, Union

from pydantic import BaseModel, Field


class IngestError(Exception):
    """La entrega no se pudo obtener o es inválida (culpa de la entrada)."""


class GitHubPublicSource(BaseModel):
    kind: Literal["github_public"] = "github_public"
    repo: str = Field(description="owner/name de un repo público de GitHub")
    sha: str = Field(description="SHA de commit completo (40 hex)")


class ZipSource(BaseModel):
    kind: Literal["zip"] = "zip"
    path: Path = Field(description="Ruta local al .zip ya recibido")



SubmissionSource = Annotated[
    Union[GitHubPublicSource, ZipSource],
    Field(discriminator="kind"),
]


@dataclass(frozen=True)
class Workspace:
    """Contenido de una entrega materializado en disco."""

    path: Path
    content_hash: str
    source: dict = field(default_factory=dict)
    size_bytes: int = 0


class Fetcher(Protocol):
    """Materializa una fuente en `dest` (directorio vacío que ya existe)."""

    def fetch(self, source: BaseModel, dest: Path) -> None: ...


def rmtree_force(path: Path) -> None:
    """`shutil.rmtree` que también borra archivos de solo lectura (packs de git en Windows)."""

    def onexc(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=onexc)
        else:  # Debian 12 en la VM trae Python 3.11
            shutil.rmtree(path, onerror=onexc)
