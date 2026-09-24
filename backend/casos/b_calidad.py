def aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]:
    """Aplica un descuento porcentual a cada precio y redondea a 2 decimales."""
    resultado = []
    i = 0
    while i < len(precios):
        precio = precios[i]
        resultado.append(round(precio * (1 - porcentaje / 100), 2))
    return resultado
