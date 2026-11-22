"""Acuerdo nuevo: mediana(numeros). 3 entregas correctas y 7 que no deben aprobarse."""

NOMBRE = "mediana"

ACUERDO = {
    "description": "Módulo estadistica.py con la función mediana(numeros: list[float]) -> float, que devuelve la mediana de una lista de números.",
    "criteria": [
        "Con una cantidad impar de elementos devuelve el elemento central de la lista ordenada de menor a mayor.",
        "Con una cantidad par de elementos devuelve el promedio (suma / 2, con división real) de los dos elementos centrales de la lista ordenada.",
        "No modifica la lista que recibe: no la ordena en su lugar ni le quita o agrega elementos.",
        "Si la lista está vacía lanza ValueError.",
        "Funciona con enteros, con floats y con valores negativos.",
        "Solo puede importar el módulo statistics.",
    ],
    "language": "python",
    "allowed_deps": ["statistics"],
    "examples": [
        {"input": "mediana([3, 1, 2])", "output": "2"},
        {"input": "mediana([4, 1, 3, 2])", "output": "2.5"},
        {"input": "mediana([])", "output": "raises ValueError"},
    ],
    "interface": {"language": "python", "symbols": [{
        "module": "estadistica", "name": "mediana", "kind": "function",
        "signature": "mediana(numeros: list[float]) -> float"}]},
}


def _e(id_, aprobar, motivo, code):
    return {"id": id_, "aprobar": aprobar, "motivo": motivo, "files": {"estadistica.py": code}}


ENTREGAS = [
    _e("correcta", True, "correcta", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        raise ValueError("la lista está vacía")
    orden = sorted(numeros)
    medio = len(orden) // 2
    if len(orden) % 2:
        return orden[medio]
    return (orden[medio - 1] + orden[medio]) / 2
'''),
    _e("correcta-statistics", True, "correcta con statistics.median (StatisticsError hereda de ValueError)", '''\
import statistics


def mediana(numeros: list[float]) -> float:
    return statistics.median(numeros)
'''),
    _e("correcta-copia", True, "correcta, ordena una copia", '''\
def mediana(numeros: list[float]) -> float:
    """Mediana sin tocar la lista original."""
    copia = list(numeros)
    if len(copia) == 0:
        raise ValueError("no hay datos")
    copia.sort()
    n = len(copia)
    return copia[n // 2] if n % 2 == 1 else (copia[n // 2 - 1] + copia[n // 2]) / 2
'''),
    _e("sin-ordenar", False, "no ordena la lista", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        raise ValueError("vacía")
    medio = len(numeros) // 2
    if len(numeros) % 2:
        return numeros[medio]
    return (numeros[medio - 1] + numeros[medio]) / 2
'''),
    _e("par-toma-el-menor", False, "con cantidad par devuelve el central menor", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        raise ValueError("vacía")
    orden = sorted(numeros)
    return orden[(len(orden) - 1) // 2]
'''),
    _e("division-entera", False, "promedia con // (2 en lugar de 2.5)", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        raise ValueError("vacía")
    orden = sorted(numeros)
    medio = len(orden) // 2
    if len(orden) % 2:
        return orden[medio]
    return (orden[medio - 1] + orden[medio]) // 2
'''),
    _e("ordena-en-su-lugar", False, "modifica la lista del cliente con sort()", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        raise ValueError("vacía")
    numeros.sort()
    medio = len(numeros) // 2
    if len(numeros) % 2:
        return numeros[medio]
    return (numeros[medio - 1] + numeros[medio]) / 2
'''),
    _e("vacia-devuelve-none", False, "lista vacía devuelve None", '''\
def mediana(numeros: list[float]) -> float:
    if not numeros:
        return None
    orden = sorted(numeros)
    medio = len(orden) // 2
    if len(orden) % 2:
        return orden[medio]
    return (orden[medio - 1] + orden[medio]) / 2
'''),
    _e("vacia-indexerror", False, "lista vacía lanza IndexError", '''\
def mediana(numeros: list[float]) -> float:
    orden = sorted(numeros)
    medio = len(orden) // 2
    if len(orden) % 2:
        return orden[medio]
    return (orden[medio - 1] + orden[medio]) / 2
'''),
    _e("memoriza-ejemplos", False, "responde los ejemplos públicos de memoria", '''\
def mediana(numeros: list[float]) -> float:
    if numeros == [3, 1, 2]:
        return 2
    if numeros == [4, 1, 3, 2]:
        return 2.5
    if not numeros:
        raise ValueError("vacía")
    return numeros[0]
'''),
]
