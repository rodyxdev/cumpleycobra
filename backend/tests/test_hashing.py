"""Helper de hashes y JSON canónico."""

import unicodedata

import pytest

from backend.hashing import canonical_bytes, code_hash, rules_hash, sha256_hex, verdict_hash
from backend.plantilla import DEMO_SPEC


def test_float_es_error():
    with pytest.raises(TypeError):
        canonical_bytes({"amount": 1.5})


def test_float_anidado_es_error():
    with pytest.raises(TypeError):
        canonical_bytes({"a": [1, {"b": 0.1}]})
    with pytest.raises(TypeError):
        rules_hash({**DEMO_SPEC, "examples": [{"input": 1.0, "output": "x"}]})


def test_nfc_mismo_hash_para_formas_equivalentes():
    compuesta = unicodedata.normalize("NFC", "canción")      # ó como un solo punto de código
    descompuesta = unicodedata.normalize("NFD", "canción")   # o + acento combinante
    assert compuesta != descompuesta
    assert canonical_bytes({"t": compuesta}) == canonical_bytes({"t": descompuesta})
    # También en las claves.
    assert canonical_bytes({compuesta: 1}) == canonical_bytes({descompuesta: 1})


def test_mismo_hash_con_claves_en_otro_orden():
    a = {"b": 1, "a": {"y": [1, 2], "x": True}, "c": None}
    b = {"c": None, "a": {"x": True, "y": [1, 2]}, "b": 1}
    assert canonical_bytes(a) == canonical_bytes(b)
    assert sha256_hex(canonical_bytes(a)) == sha256_hex(canonical_bytes(b))


def test_formato_canonico_exacto():
    esperado = '{"a":[1,true,null],"b":"ñ"}'.encode("utf-8")
    assert canonical_bytes({"b": "ñ", "a": [1, True, None]}) == esperado


def test_rules_hash_ordena_allowed_deps_e_ignora_raw_request():
    s1 = {**DEMO_SPEC, "allowed_deps": ["math", "json"]}
    s2 = {**DEMO_SPEC, "allowed_deps": ["json", "math"], "raw_request": "otro texto"}
    assert rules_hash(s1) == rules_hash(s2)
    assert rules_hash(s1) != rules_hash(DEMO_SPEC)


def test_rules_hash_cambia_si_cambia_un_criterio():
    otro = {**DEMO_SPEC, "criteria": DEMO_SPEC["criteria"][:-1]}
    assert rules_hash(otro) != rules_hash(DEMO_SPEC)


def test_code_hash_sobre_bytes_sin_limpiar():
    assert code_hash("x = 1\n") == sha256_hex(b"x = 1\n")
    assert code_hash("x = 1  # c\n") != code_hash("x = 1\n")


def test_verdict_hash_estable_y_sensible():
    base = dict(task_id="t", code_hash="00" * 32, approved=True, reason="ok", stage="llm",
                comparison=["✓ Criterio 1: sí"], security_flags=[], video_url=None)
    assert verdict_hash(**base) == verdict_hash(**dict(reversed(list(base.items()))))
    assert verdict_hash(**base) != verdict_hash(**{**base, "approved": False})
    assert len(verdict_hash(**base)) == 64
