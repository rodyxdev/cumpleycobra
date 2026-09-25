"""Pedido de la demo y plantilla fija de respaldo del pedido asistido."""

DEMO_RAW_REQUEST = (
    "Necesito una función en Python que reciba una lista de precios y un porcentaje "
    "de descuento, y me regrese los precios con el descuento aplicado, redondeados "
    "a 2 decimales. Sin librerías externas."
)

DEMO_SPEC = {
    "description": (
        "Implementar en Python la función aplicar_descuento(precios: list[float], "
        "porcentaje: float) -> list[float], que devuelve cada precio con el "
        "descuento aplicado, redondeado a 2 decimales, sin dependencias externas."
    ),
    "criteria": [
        "Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].",
        "Cada precio de salida es igual a precio * (1 - porcentaje / 100).",
        "Cada precio de salida está redondeado a 2 decimales.",
        "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.",
        "No importa ningún módulo (sin dependencias externas).",
        "La función termina para cualquier lista de entrada (sin bucles infinitos).",
    ],
    "language": "python",
    "allowed_deps": [],
    "examples": [
        {"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"},
        {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"},
        {"input": "aplicar_descuento([], 20.0)", "output": "[]"},
    ],
}
