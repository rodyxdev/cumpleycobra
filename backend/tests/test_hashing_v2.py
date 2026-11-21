"""Comparación con el JSON canónico de v2 (cumpleycobra-v2, backend/canonical.py).

Decisión del plan de mejora: se queda `hashing.py` (las tareas existentes dependen de él) con los
mismos rechazos que v2. Aquí se demuestra que, con datos válidos, los bytes son idénticos: la
implementación de referencia de abajo es una copia fiel del codificador de v2 (escrito sin json.dumps).
"""
import unicodedata

import pytest

from backend.hashing import canonical_bytes, rules_hash, verdict_hash

# --- Referencia: codificador de v2 ---------------------------------------------------------
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _v2_string(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        elif 0xD800 <= code <= 0xDFFF:
            raise ValueError("surrogate")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def v2_canonical(value) -> bytes:
    def enc(v):
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, int):
            if not -(2**53 - 1) <= v <= 2**53 - 1:
                raise ValueError("int")
            return str(int(v))
        if isinstance(v, float):
            raise ValueError("float")
        if isinstance(v, str):
            return _v2_string(v)
        if isinstance(v, (list, tuple)):
            return "[" + ",".join(enc(x) for x in v) + "]"
        if isinstance(v, dict):
            items = {}
            for k, x in v.items():
                if not isinstance(k, str):
                    raise ValueError("key")
                nk = unicodedata.normalize("NFC", k)
                if nk in items:
                    raise ValueError("dup")
                items[nk] = x
            return "{" + ",".join(f"{_v2_string(k)}:{enc(items[k])}" for k in sorted(items)) + "}"
        raise ValueError("type")
    return enc(value).encode("utf-8")


# --- Vectores -------------------------------------------------------------------------------
VECTORES = [
    {},
    [],
    {"b": 1, "a": [True, False, None], "c": {"z": "", "y": 0}},
    {"texto": 'comillas " y barra \\ y / normal'},
    {"control": "\b\f\n\r\t\u0000\u0001\u001f\u007f fin"},
    {"nfd": "café", "nfc": "café", "ñ": "año", "emoji": "✓ ✗ 🚀"},
    {" ": "separadores    ", "zz": "ＺＥＮ", "Z": 1, "a": 2, "É": 3, "éx": 4},
    {"enteros": [0, -1, 1, 10_000_000, 2**53 - 1, -(2**53 - 1)]},
    {"anidado": [[[{"k": ["v", {"x": [1, 2, 3]}]}]]]},
    {"version": 1, "description": "Implementar aplicar_descuento", "criteria": ["c1", "c2"],
     "language": "python", "allowed_deps": [], "examples": [{"input": "[100]", "output": "[90.0]"}]},
]


@pytest.mark.parametrize("valor", VECTORES)
def test_mismos_bytes_que_v2(valor):
    assert canonical_bytes(valor) == v2_canonical(valor)


@pytest.mark.parametrize("valor", [
    {"x": 1.5}, {"x": 2**53}, {"x": -(2**53)}, {"x": "\ud800"}, {1: "clave no texto"},
    {"café": 1, "café": 2},
])
def test_rechaza_lo_mismo_que_v2(valor):
    with pytest.raises(ValueError):
        v2_canonical(valor)
    with pytest.raises((TypeError, ValueError)):
        canonical_bytes(valor)


def test_hashes_existentes_no_cambian():
    """Hashes reales calculados antes de este cambio (tarea de la demo en testnet)."""
    from backend.plantilla import DEMO_SPEC
    assert rules_hash(DEMO_SPEC) == "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
    assert len(verdict_hash(task_id="t", code_hash="0" * 64, approved=True, reason="r", stage="llm",
                            comparison=["✓ a"], security_flags=[], video_url=None)) == 64
