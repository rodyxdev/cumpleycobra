"""Capa de entrada: convierte una fuente (repo público + SHA, o ZIP) en un `Workspace` con hash.

La GitHub App de v2 (repos privados) queda para después (plan de mejora, fase 3).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from verifier.config import get_settings
from verifier.ingest.base import (
    Fetcher,
    GitHubPublicSource,
    IngestError,
    SubmissionSource,
    Workspace,
    ZipSource,
    rmtree_force,
)
from verifier.ingest.github_public import GitHubPublicFetcher
from verifier.ingest.hashing import hash_workspace, tree_size
from verifier.ingest.zip_upload import ZipFetcher

FETCHERS: dict[str, Fetcher] = {
    "github_public": GitHubPublicFetcher(),
    "zip": ZipFetcher(),
}


def _describe(source: GitHubPublicSource | ZipSource) -> dict:
    # La ruta local del ZIP es un detalle del servidor; no se expone.
    return source.model_dump(mode="json", exclude={"path"})


def fetch_submission(source: GitHubPublicSource | ZipSource, dest_root: Path | None = None) -> Workspace:
    """Materializa la entrega en un directorio nuevo y calcula su hash de contenido.

    Si algo falla, el directorio parcial se borra y se propaga la excepción.
    """
    s = get_settings()
    dest_root = dest_root or s.work_dir / "workspaces"
    dest = dest_root / uuid.uuid4().hex
    dest.mkdir(parents=True)
    try:
        FETCHERS[source.kind].fetch(source, dest)
        size = tree_size(dest)
        if size > s.workspace_max_bytes:
            raise IngestError(f"el workspace supera {s.workspace_max_bytes} bytes")
        return Workspace(path=dest, content_hash=hash_workspace(dest), source=_describe(source), size_bytes=size)
    except BaseException:
        rmtree_force(dest)
        raise


__all__ = [
    "GitHubPublicSource",
    "IngestError",
    "SubmissionSource",
    "Workspace",
    "ZipSource",
    "fetch_submission",
    "hash_workspace",
    "rmtree_force",
]
