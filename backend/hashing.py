"""JSON canónico y SHA-256: el único helper de hashes de todo el backend."""

import hashlib
import json
import unicodedata


MAX_SAFE_INT = 2**53 - 1  # mismo rango que JSON en cualquier lenguaje (y que canonical.py de v2)


def _normalize(obj):
    """NFC en textos y validación. Con datos válidos, los bytes son los mismos que en canonical.py de v2.

    Rechazos (los mismos de v2): float, enteros fuera de ±(2^53 − 1), surrogates sueltos, claves
    que no son texto y claves que coinciden tras NFC. Ninguno cambia el hash de datos que antes
    eran válidos: solo convierten en error lo que antes se hasheaba de forma ambigua.
    """
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        raise TypeError("No se permiten float en datos que se hashean")
    if isinstance(obj, int):
        if not -MAX_SAFE_INT <= obj <= MAX_SAFE_INT:
            raise ValueError("Entero fuera del rango seguro de JSON (±(2^53 − 1))")
        return obj
    if isinstance(obj, str):
        text = unicodedata.normalize("NFC", obj)
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
            raise ValueError("Surrogate suelto: no es UTF-8 válido")
        return text
    if isinstance(obj, (list, tuple)):
        return [_normalize(x) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("Las claves de los objetos que se hashean deben ser texto")
            nkey = _normalize(key)
            if nkey in out:
                raise ValueError(f"Claves duplicadas tras NFC: {key!r}")
            out[nkey] = _normalize(value)
        return out
    raise TypeError(f"Tipo no soportado en datos que se hashean: {type(obj).__name__}")


def canonical_bytes(obj) -> bytes:
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rules_hash(spec: dict) -> str:
    """Hash de la versión final acordada (el pedido original no entra).

    `version: 1` para las tareas de v1. Una tarea con verificación por ejecución (fase 3) usa
    `version: 2`: el mismo objeto más `verification` e `interface` (lo que la entrega debe exponer).
    """
    agreed = {
        "version": 1,
        "description": spec["description"],
        "criteria": spec["criteria"],
        "language": spec["language"],
        "allowed_deps": sorted(spec["allowed_deps"]),
        "examples": spec["examples"],
    }
    if spec.get("verification") == "execution":
        agreed.update(version=2, verification="execution", interface=spec["interface"])
    return sha256_hex(canonical_bytes(agreed))


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


def verdict_hash_v2(*, task_id: str, rules_hash: str, suite_hash: str, workspace_hash: str,
                    approved: bool, stage: str, criteria: list, video_url) -> str:
    """Veredicto por ejecución (fase 3). `criteria` = [{"index", "status"}] en el orden acordado."""
    return sha256_hex(canonical_bytes({
        "version": 2,
        "task_id": task_id,
        "rules_hash": rules_hash,
        "suite_hash": suite_hash,
        "workspace_hash": workspace_hash,
        "approved": approved,
        "stage": stage,
        "criteria": criteria,
        "video_url": video_url,
    }))


def suite_hash(files: dict[str, str]) -> str:
    """Hash de la suite oculta completa (infraestructura fija + tests generados + clasificación)."""
    return sha256_hex(canonical_bytes({"version": 1, "files": files}))
