"""Archivos fijos de la suite oculta: los escribe Cumple&Cobra, nunca el modelo ni el programador.

Corren en el contenedor CONFIABLE, que no monta la entrega: los tests solo la alcanzan por
`cc_channel`. La API calcula el `suite_hash` sobre estos mismos textos más los tests generados.
"""

from __future__ import annotations

from pathlib import Path

CONFTEST = '''"""Infraestructura de Cumple&Cobra (no generada por el modelo). Lado confiable."""
import sys

sys.path.insert(0, "/cc")
import cc_channel  # noqa: E402


def pytest_sessionstart(session):
    if not cc_channel.wait_ready(20.0):
        print("AVISO: la entrega no aceptó conexiones en 20 s", file=sys.stderr)
'''

PYTEST_INI = "[pytest]\njunit_family = xunit1\n"


def suite_files(tests: dict[str, str]) -> dict[str, str]:
    """Todos los archivos de la suite: la infraestructura fija más los tests generados."""
    reserved = {"conftest.py", "pytest.ini"} & set(tests)
    if reserved:
        raise ValueError(f"nombres reservados en la suite: {sorted(reserved)}")
    return {"conftest.py": CONFTEST, "pytest.ini": PYTEST_INI, **tests}


def write_suite_dir(dest: Path, tests: dict[str, str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, code in suite_files(tests).items():
        if "/" in name or "\\" in name or not name.endswith((".py", ".ini")):
            raise ValueError(f"nombre de archivo de suite inválido: {name!r}")
        (dest / name).write_text(code, encoding="utf-8", newline="\n")
