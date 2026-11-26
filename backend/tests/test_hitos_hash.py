"""Pruebas del rules_hash versión 3 por hito (etapa 2, docs/hitos/diseno.md).

Comprueba que:
- ningún hash v1 ni v2 existente cambia (valores dorados fijos);
- el hash v3 incluye `version: 3` y `hito: {"proyecto", "indice", "de", "titulo"}`
  encima del objeto de v1 o de v2 (script y web);
- hitos con los mismos criterios pero distinto índice, título, total o proyecto
  producen hashes distintos.
"""

import pytest

from backend.hashing import canonical_bytes, milestone_rules_hash, rules_hash, sha256_hex
from backend.plantilla import DEMO_SPEC

INTERFACE = {
    "language": "python",
    "symbols": [{
        "module": "descuentos",
        "name": "aplicar_descuento",
        "kind": "function",
        "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]",
        "description": "Devuelve cada precio con el descuento aplicado, redondeado a 2 decimales.",
    }],
}
EXEC_SPEC = {**DEMO_SPEC, "verification": "execution", "interface": INTERFACE}
WEB_SPEC = {
    "description": "Landing de café",
    "criteria": ["Muestra el título Café Luna"],
    "language": "web",
    "allowed_deps": [],
    "examples": [],
    "verification": "execution",
    "interface": None,
    "web": {"pages": ["/"]},
}


def test_hashes_v1_y_v2_existentes_no_cambian():
    assert rules_hash(DEMO_SPEC) == "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
    assert rules_hash(EXEC_SPEC) == "0a9cb54ca20ea621613636b50a3ad6c3cbce602a649067a2e0347c966017f1a8"
    assert rules_hash(WEB_SPEC) == "0d248a2747cfdf1ba210f1d452d29f3c67b63e962eb6251632ec575f0e8adea0"


def test_hash_v3_estatico_coincide_con_esquema_canonico():
    hito = {"proyecto": "proy-1", "indice": 0, "de": 3, "titulo": "Estructura"}
    esperado = sha256_hex(canonical_bytes({
        "version": 3,
        "description": DEMO_SPEC["description"],
        "criteria": DEMO_SPEC["criteria"],
        "language": DEMO_SPEC["language"],
        "allowed_deps": sorted(DEMO_SPEC["allowed_deps"]),
        "examples": DEMO_SPEC["examples"],
        "hito": hito,
    }))
    assert milestone_rules_hash(DEMO_SPEC, **hito) == esperado
    assert rules_hash(DEMO_SPEC, hito=hito) == esperado
    assert rules_hash({**DEMO_SPEC, "hito": hito}) == esperado
    assert esperado != rules_hash(DEMO_SPEC)


def test_hash_v3_ejecucion_script_y_web_conservan_campos_de_v2():
    hito = {"proyecto": "proy-2", "indice": 1, "de": 2, "titulo": "Lógica"}
    esperado_script = sha256_hex(canonical_bytes({
        "version": 3,
        "description": EXEC_SPEC["description"],
        "criteria": EXEC_SPEC["criteria"],
        "language": EXEC_SPEC["language"],
        "allowed_deps": sorted(EXEC_SPEC["allowed_deps"]),
        "examples": EXEC_SPEC["examples"],
        "verification": "execution",
        "interface": INTERFACE,
        "hito": hito,
    }))
    assert milestone_rules_hash(EXEC_SPEC, **hito) == esperado_script
    assert esperado_script != rules_hash(EXEC_SPEC)

    esperado_web = sha256_hex(canonical_bytes({
        "version": 3,
        "description": WEB_SPEC["description"],
        "criteria": WEB_SPEC["criteria"],
        "language": WEB_SPEC["language"],
        "allowed_deps": [],
        "examples": [],
        "verification": "execution",
        "interface": None,
        "web": {"pages": ["/"]},
        "hito": hito,
    }))
    assert milestone_rules_hash(WEB_SPEC, **hito) == esperado_web
    assert esperado_web != rules_hash(WEB_SPEC)


def test_hitos_con_mismos_criterios_tienen_hashes_distintos():
    h0 = milestone_rules_hash(DEMO_SPEC, proyecto="p1", indice=0, de=2, titulo="Parte")
    h1 = milestone_rules_hash(DEMO_SPEC, proyecto="p1", indice=1, de=2, titulo="Parte")
    h_otro_titulo = milestone_rules_hash(DEMO_SPEC, proyecto="p1", indice=0, de=2, titulo="Otra")
    h_otro_total = milestone_rules_hash(DEMO_SPEC, proyecto="p1", indice=0, de=3, titulo="Parte")
    h_otro_proy = milestone_rules_hash(DEMO_SPEC, proyecto="p2", indice=0, de=2, titulo="Parte")
    assert len({h0, h1, h_otro_titulo, h_otro_total, h_otro_proy}) == 5


def test_hash_v3_rechaza_float_en_hito():
    with pytest.raises(TypeError):
        rules_hash(DEMO_SPEC, hito={"proyecto": "p1", "indice": 0.0, "de": 2, "titulo": "A"})
