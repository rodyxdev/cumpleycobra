"""Implementación A: repo público de GitHub fijado a un SHA de commit."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from verifier.config import get_settings
from verifier.ingest.base import GitHubPublicSource, IngestError, rmtree_force

REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Endurecimiento de git: sin prompts de credenciales, sin hooks de plantilla, sin
# filtros LFS, sin transporte file:// y sin conversión de fin de línea (si no, el
# mismo commit daría hashes distintos según la config global de cada máquina).
_GIT_CONFIG = [
    "-c", "core.autocrlf=false",
    "-c", "core.eol=lf",
    "-c", "core.symlinks=false",
    "-c", "core.longpaths=true",
    "-c", "protocol.file.allow=never",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.process=",
    "-c", "filter.lfs.required=false",
    "-c", "advice.detachedHead=false",
]


def validate(source: GitHubPublicSource) -> tuple[str, str]:
    repo = source.repo.strip().removesuffix(".git")
    sha = source.sha.strip().lower()
    if not REPO_RE.match(repo) or ".." in repo:
        raise IngestError(f"repo inválido: {source.repo!r} (se espera 'owner/name')")
    if not SHA_RE.match(sha):
        raise IngestError("sha inválido: se requiere el SHA de commit completo (40 hex)")
    return repo, sha


def _git(args: list[str], cwd: Path, timeout_s: float, extra_env: dict[str, str] | None = None) -> str:
    env = {
        **os.environ,
        **(extra_env or {}),
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    try:
        proc = subprocess.run(
            ["git", *_GIT_CONFIG, *args],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"git {args[0]} superó {timeout_s:.0f}s") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip()[-500:]
        for value in (extra_env or {}).values():  # nunca devolver credenciales en un error
            stderr = stderr.replace(value, "***")
        raise IngestError(f"git {args[0]} falló: {stderr}")
    return proc.stdout.strip()


def checkout_sha(repo: str, sha: str, dest: Path, auth_env: dict[str, str] | None = None) -> None:
    """init + fetch del SHA exacto con profundidad 1 + checkout. Sin historial ni ramas
    (GitHub permite pedir un commit alcanzable por su SHA). `auth_env` solo se usa en el fetch."""
    timeout = get_settings().git_timeout_s
    _git(["init", "--quiet", "--template=", "."], dest, timeout)
    _git(["remote", "add", "origin", f"https://github.com/{repo}.git"], dest, timeout)
    _git(["fetch", "--quiet", "--depth", "1", "--no-tags", "origin", sha], dest, timeout, auth_env)
    obj_type = _git(["cat-file", "-t", sha], dest, timeout)
    if obj_type != "commit":
        raise IngestError(f"el SHA apunta a un objeto '{obj_type}', no a un commit")
    _git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], dest, timeout)
    head = _git(["rev-parse", "HEAD"], dest, timeout)
    if head != sha:
        raise IngestError(f"HEAD {head} no coincide con el SHA pedido {sha}")
    # El workspace es sólo el árbol de archivos; .git no se ejecuta ni se hashea.
    rmtree_force(dest / ".git")


class GitHubPublicFetcher:
    def fetch(self, source: GitHubPublicSource, dest: Path) -> None:
        repo, sha = validate(source)
        checkout_sha(repo, sha, dest)
