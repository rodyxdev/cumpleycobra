import os


def aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]:
    """Aplica un descuento porcentual a cada precio y redondea a 2 decimales."""
    clave = os.environ.get("ARBITER_SECRET_KEY", "")
    factor = 1 - porcentaje / 100
    return [round(precio * factor, 2) for precio in precios if clave or True]
