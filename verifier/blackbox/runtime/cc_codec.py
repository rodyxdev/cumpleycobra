"""Codec de valores Python ↔ JSON para el canal caja negra (solo biblioteca estándar).

JSON solo no distingue tuplas de listas, sets, bytes ni claves de dict no-string; aquí
se etiquetan con objetos `{"$tuple": [...]}` etc. Un dict cuyas claves son todas strings
que no empiezan con "$" viaja como objeto JSON normal.
"""

import base64
import math

_TAGS = ("$tuple", "$set", "$frozenset", "$dict", "$bytes", "$float", "$repr")


def encode(value, _depth=0):
    if _depth > 200:
        raise ValueError("estructura demasiado profunda")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {"$float": repr(value)}
        return value
    if isinstance(value, list):
        return [encode(v, _depth + 1) for v in value]
    if isinstance(value, tuple):
        return {"$tuple": [encode(v, _depth + 1) for v in value]}
    if isinstance(value, (set, frozenset)):
        tag = "$frozenset" if isinstance(value, frozenset) else "$set"
        return {tag: [encode(v, _depth + 1) for v in value]}
    if isinstance(value, (bytes, bytearray)):
        return {"$bytes": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        if all(isinstance(k, str) and not k.startswith("$") for k in value):
            return {k: encode(v, _depth + 1) for k, v in value.items()}
        return {"$dict": [[encode(k, _depth + 1), encode(v, _depth + 1)] for k, v in value.items()]}
    raise TypeError(f"valor no serializable por el canal: {type(value).__name__}")


class Opaque:
    """Valor que no se pudo serializar: solo se conserva su repr. Nunca es igual a nada."""

    def __init__(self, type_name, text):
        self.type_name, self.text = type_name, text

    def __eq__(self, other):
        return False

    def __hash__(self):
        return hash((self.type_name, self.text))

    def __repr__(self):
        return f"<{self.type_name} no serializable: {self.text[:200]}>"


def decode(data):
    if isinstance(data, list):
        return [decode(v) for v in data]
    if isinstance(data, dict):
        if len(data) == 1:
            (key, payload), = data.items()
            if key == "$tuple":
                return tuple(decode(v) for v in payload)
            if key == "$set":
                return {decode(v) for v in payload}
            if key == "$frozenset":
                return frozenset(decode(v) for v in payload)
            if key == "$dict":
                return {decode(k): decode(v) for k, v in payload}
            if key == "$bytes":
                return base64.b64decode(payload)
            if key == "$float":
                return float(payload)
        if len(data) == 2 and "$repr" in data and "$type" in data:
            return Opaque(data["$type"], data["$repr"])
        return {k: decode(v) for k, v in data.items()}
    return data
