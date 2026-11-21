"""Implementación B: archivo ZIP subido por el freelancer.

Defensas:
- zip-slip: se rechazan rutas absolutas, con unidad (`C:`), con `..`, con `:` (ADS de
  NTFS) o nombres reservados de Windows; además se comprueba que el destino resuelto
  quede dentro de `dest`.
- symlinks: se rechazan las entradas marcadas como enlace simbólico.
- zip bomb: límite de tamaño del .zip, de número de entradas y de bytes descomprimidos
  (contados mientras se escribe, sin fiarse de la cabecera).
- entradas duplicadas: se rechazan (una podría pisar a otra).

Si todas las entradas cuelgan de un único directorio raíz (lo típico de "Descargar
ZIP" en GitHub), ese prefijo se elimina, para que el mismo código dé el mismo hash
venga por ZIP o por git.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from verifier.config import get_settings
from verifier.ingest.base import IngestError, ZipSource

_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_CHUNK = 64 * 1024


def safe_member_parts(name: str) -> tuple[str, ...]:
    """Valida el nombre de una entrada y devuelve sus componentes; lanza IngestError si es peligroso."""
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\0" in normalized:
        raise IngestError(f"ruta no permitida en el ZIP: {name!r}")
    parts = tuple(p for p in PurePosixPath(normalized).parts if p not in ("", "."))
    for part in parts:
        if part == ".." or ":" in part:
            raise IngestError(f"ruta no permitida en el ZIP: {name!r}")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED or part.endswith((" ", ".")):
            raise IngestError(f"nombre no permitido en Windows: {name!r}")
    return parts


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _common_root(members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]]) -> str | None:
    tops = {parts[0] for _, parts in members if parts}
    if len(tops) != 1:
        return None
    top = next(iter(tops))
    # Sólo se quita si es un directorio (ninguna entrada es exactamente ese nombre como archivo).
    for info, parts in members:
        if len(parts) == 1 and not info.is_dir():
            return None
    return top


class ZipFetcher:
    def fetch(self, source: ZipSource, dest: Path) -> None:
        s = get_settings()
        zip_path = Path(source.path)
        if zip_path.stat().st_size > s.zip_max_upload_bytes:
            raise IngestError(f"el ZIP supera {s.zip_max_upload_bytes} bytes")
        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as exc:
            raise IngestError("el archivo no es un ZIP válido") from exc

        with zf:
            infos = zf.infolist()
            if len(infos) > s.zip_max_files:
                raise IngestError(f"el ZIP tiene más de {s.zip_max_files} entradas")

            members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
            for info in infos:
                if _is_symlink(info):
                    raise IngestError(f"el ZIP contiene un symlink: {info.filename!r}")
                if info.flag_bits & 0x1:
                    raise IngestError("el ZIP está cifrado")
                members.append((info, safe_member_parts(info.filename)))

            root = _common_root(members)
            dest_resolved = dest.resolve()
            seen: set[str] = set()
            written = 0

            for info, parts in members:
                if root is not None:
                    parts = parts[1:]
                if not parts:
                    continue
                target = dest_resolved.joinpath(*parts).resolve()
                if not target.is_relative_to(dest_resolved) or target == dest_resolved:
                    raise IngestError(f"ruta fuera del workspace: {info.filename!r}")
                key = "/".join(parts).lower()  # Windows no distingue mayúsculas
                if key in seen:
                    raise IngestError(f"entrada duplicada en el ZIP: {info.filename!r}")
                seen.add(key)

                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        written += len(chunk)
                        if written > s.zip_max_uncompressed_bytes:
                            raise IngestError(
                                f"el contenido descomprimido supera {s.zip_max_uncompressed_bytes} bytes"
                            )
                        out.write(chunk)
