"""Acuerdo de la demo (aplicar_descuento) con las 20 entregas del corpus del motor de v1."""

import json
from pathlib import Path

from backend.plantilla import DEMO_SPEC

ROOT = Path(__file__).resolve().parents[2]
NOMBRE = "descuentos"

ACUERDO = {
    **DEMO_SPEC,
    "interface": {"language": "python", "symbols": [{
        "module": "descuentos", "name": "aplicar_descuento", "kind": "function",
        "signature": "aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]"}]},
}

MOTIVOS = {
    "B": "bucle sin incremento: no termina", "C": "inyección en el docstring", "D": "lee os.environ",
    "K": "suma en lugar de restar", "L": "no redondea", "M": "invierte el orden", "N": "descuento fijo",
    "O": "redondea a entero", "P": "devuelve un generador", "Q": "lista vacía devuelve None",
    "R": "usa eval", "S": "accede a dunders", "T": "escribe archivos",
}


def _entregas():
    out = []
    for caso in json.loads((ROOT / "scripts" / "corpus_motor.json").read_text(encoding="utf-8")):
        code = caso.get("code") or (ROOT / caso["file"]).read_text(encoding="utf-8")
        out.append({"id": caso["id"], "aprobar": caso["approved"],
                    "motivo": "correcta" if caso["approved"] else MOTIVOS.get(caso["id"][0], "incorrecta"),
                    "files": {"descuentos.py": code}})
    return out


ENTREGAS = _entregas()
