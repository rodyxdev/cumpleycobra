"""Hash determinista del contenido de un workspace.

Mismo conjunto de (ruta relativa, bytes) → mismo hash, sin importar el orden del
sistema de archivos, las fechas de modificación ni el separador de rutas del SO.

Formato: sha256 sobre líneas `<ruta posix>\\0<tipo>\\0<sha256 del contenido>\\n`,
ordenadas por ruta (bytes UTF-8). `<tipo>` es `f` (archivo) o `l` (symlink; se
hashea el destino del enlace, nunca se sigue). Se ignoran los directorios vacíos
y el directorio `.git`. Los permisos (bit ejecutable) NO forman parte del hash:
en Windows no son fiables.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

HASH_PREFIX = "sha256:"
EXCLUDED_DIRS = {".git"}
_CHUNK = 1024 * 1024


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def iter_entries(root: Path) -> list[tuple[str, str, str]]:
    """Devuelve `(ruta_posix, tipo, digest)` de cada archivo bajo `root`, ordenado."""
    entries: list[tuple[str, str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        base = Path(dirpath)
        # os.walk lista los symlinks a directorios en dirnames; los tratamos como enlaces.
        for name in [d for d in dirnames if (base / d).is_symlink()]:
            dirnames.remove(name)
            filenames.append(name)
        for name in filenames:
            full = base / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                target = os.readlink(full).replace("\\", "/")
                entries.append((rel, "l", hashlib.sha256(target.encode("utf-8")).hexdigest()))
            else:
                entries.append((rel, "f", _file_digest(full)))
    entries.sort(key=lambda e: e[0].encode("utf-8"))
    return entries


def hash_workspace(root: Path) -> str:
    h = hashlib.sha256()
    for rel, kind, digest in iter_entries(root):
        h.update(f"{rel}\0{kind}\0{digest}\n".encode("utf-8"))
    return HASH_PREFIX + h.hexdigest()


def deterministic_zip(root: Path) -> bytes:
    """ZIP del workspace con orden, fechas y permisos fijos: mismo contenido → mismos bytes.

    Al extraerlo, `hash_workspace` da exactamente el mismo hash que el workspace original.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, kind, _digest in iter_entries(root):
            if kind != "f":
                continue
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (root / rel).read_bytes())
    return buf.getvalue()


def tree_size(root: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                total += p.stat().st_size
    return total
