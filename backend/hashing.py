"""JSON canónico y SHA-256: el único helper de hashes de todo el backend."""

import hashlib
import json
import unicodedata


def _normalize(obj):
    if isinstance(obj, float):
        raise TypeError("No se permiten float en datos que se hashean")
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    if isinstance(obj, dict):
        return {_normalize(k): _normalize(v) for k, v in obj.items()}
    return obj  # int, bool, None


def canonical_bytes(obj) -> bytes:
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rules_hash(spec: dict) -> str:
    """Hash de la versión final acordada (el pedido original no entra)."""
    return sha256_hex(canonical_bytes({
        "version": 1,
        "description": spec["description"],
        "criteria": spec["criteria"],
        "language": spec["language"],
        "allowed_deps": sorted(spec["allowed_deps"]),
        "examples": spec["examples"],
    }))


def code_hash(code: str) -> str:
    """Hash de los bytes UTF-8 del código tal como llegó (antes de limpiar)."""
    return sha256_hex(code.encode("utf-8"))


def verdict_hash(*, task_id: str, code_hash: str, approved: bool, reason: str,
                 stage: str, comparison: list, security_flags: list,
                 video_url) -> str:
    return sha256_hex(canonical_bytes({
        "version": 1,
        "task_id": task_id,
        "code_hash": code_hash,
        "approved": approved,
        "reason": reason,
        "stage": stage,
        "comparison": comparison,
        "security_flags": security_flags,
        "video_url": video_url,
    }))
