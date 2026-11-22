"""La capa de seguridad de v1 (`deterministic.py`) aplicada a una entrega de varios archivos.

Con el verificador el código sí se ejecuta, pero aislado. Esta capa sigue protegiendo al cliente,
que es quien va a correr el código en su máquina: los mismos imports y llamadas prohibidos de v1.
Diferencias: no hay límite de 10 KB por archivo (lo pone la ingesta) y los módulos propios de la
entrega cuentan como permitidos.
"""

from __future__ import annotations

import ast

from ..deterministic import TOO_DEEP, _Checker


def local_modules(files: dict[str, str]) -> set[str]:
    tops = set()
    for rel in files:
        if rel.endswith(".py"):
            tops.add(rel.split("/", 1)[0].removesuffix(".py"))
    return tops


def _is_own_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def security_scan(files: dict[str, str], allowed_deps: list[str]) -> list[str]:
    """Problemas de seguridad de los `.py` de la entrega (vacío si no hay)."""
    # `__future__` solo cambia cómo se compila el archivo (p. ej. `annotations`): no da acceso a nada.
    allowed = set(allowed_deps) | local_modules(files) | {"__future__"}
    problems: list[str] = []
    for rel, text in sorted(files.items()):
        # Los tests propios del programador nunca se ejecutan (aquí ni en la suite); sí se
        # escanean en busca de manipulación (`senales.py`).
        if not rel.endswith(".py") or _is_own_test(rel):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue  # la sintaxis la juzgan los tests (no importa) y el juez
        except (RecursionError, MemoryError):
            problems.append(f"{rel}: {TOO_DEEP}")
            continue
        checker = _Checker(allowed)
        try:
            checker.visit(tree)
        except (RecursionError, MemoryError):
            problems.append(f"{rel}: {TOO_DEEP}")
            continue
        problems += [f"{rel}, {p}" for p in checker.problems]
    return problems
