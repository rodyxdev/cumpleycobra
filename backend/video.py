"""Enlaces de Drive; se valida el formato sin visitar el archivo."""

import re
from urllib.parse import parse_qs, urlsplit


def normalize_video(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    url = urlsplit(value.strip())
    if (url.scheme != "https" or url.netloc != "drive.google.com"
            or url.fragment or len(value) > 1000):
        raise ValueError("Usa un enlace HTTPS de Google Drive al video")
    match = re.fullmatch(r"/file/d/([A-Za-z0-9_-]{10,200})(?:/(?:view|preview))?/?", url.path)
    file_id = match.group(1) if match else None
    if url.path in ("/open", "/uc"):
        ids = parse_qs(url.query).get("id", [])
        if len(ids) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{10,200}", ids[0]):
            file_id = ids[0]
    if not file_id:
        raise ValueError("El enlace debe apuntar a un archivo de video de Google Drive")
    return f"https://drive.google.com/file/d/{file_id}/preview"
