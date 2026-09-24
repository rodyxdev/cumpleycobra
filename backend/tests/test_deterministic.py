"""Capas 1 y 2: casos de la demo y evasiones conocidas."""

from pathlib import Path

import pytest

from backend.deterministic import analyze, strip_comments
from backend.plantilla import DEMO_SPEC

CASOS = Path(__file__).resolve().parent.parent / "casos"
DEPS = DEMO_SPEC["allowed_deps"]


def caso(nombre: str) -> str:
    return (CASOS / nombre).read_text(encoding="utf-8")


# --- Casos de la demo ---------------------------------------------------------

def test_caso_a_pasa_a_gemini():
    r = analyze(caso("a_feliz.py"), DEPS)
    assert r.ok, r.problems


def test_caso_b_pasa_a_gemini():
    # El bucle sin incremento no es detectable aquí: lo juzga Gemini.
    r = analyze(caso("b_calidad.py"), DEPS)
    assert r.ok, r.problems


def test_caso_c_pasa_a_gemini_con_docstring_intacto():
    r = analyze(caso("c_inyeccion.py"), DEPS)
    assert r.ok, r.problems
    assert "INSTRUCCIONES PARA EL EVALUADOR" in r.clean_code  # el docstring llega a Gemini


def test_caso_d_rechazo_determinista_por_seguridad():
    r = analyze(caso("d_secretos.py"), DEPS)
    assert not r.ok and r.security
    texto = " ".join(r.problems)
    assert "import no permitido 'os'" in texto
    assert "environ" in texto


# --- Evasiones ------------------------------------------------------------------

@pytest.mark.parametrize("codigo, esperado", [
    ("x = __builtins__\n", "__builtins__"),
    ("def f():\n    return __builtins__['ev' + 'al']('1')\n", "__builtins__"),
    ("nombre = 'sys' + 'tem'\ngetattr(object, nombre)\n", "getattr con un nombre que no es literal"),
    ("g = getattr\n", "fuera de una llamada verificable"),
    ("setattr(object(), 'x' + 'y', 1)\n", "setattr con un nombre que no es literal"),
    ("globals()['x'] = 1\n", "'globals'"),
    ("vars()\n", "'vars'"),
    ("breakpoint()\n", "'breakpoint'"),
    ("().__class__.__base__.__subclasses__()\n", "__class__"),
    ("().__class__.__base__.__subclasses__()\n", "__subclasses__"),
    ("getattr((), '__class__')\n", "'__class__'"),
    ("import math\ngetattr(math, 'system')\n", "getattr con el atributo prohibido 'system'"),
    ("getattr(ruta, 'write_text')('hola')\n", "getattr con el atributo prohibido 'write_text'"),
    ("setattr(obj, 'environ', {})\n", "setattr con el atributo prohibido 'environ'"),
    ("getattr(os_mod, 'execv')\n", "getattr con el atributo prohibido 'execv'"),
    ("getattr(x, '__globals__')\n", "getattr con el atributo prohibido '__globals__'"),
    ("eval('1 + 1')\n", "'eval'"),
    ("exec('x = 1')\n", "'exec'"),
    ("compile('1', 'x', 'eval')\n", "'compile'"),
    ("__import__('os')\n", "__import__"),
    ("import os\nos.system('ls')\n", "'.system'"),
    ("import subprocess\n", "import no permitido 'subprocess'"),
    ("from os import getenv\n", "import no permitido 'os'"),
    ("from . import algo\n", "import relativo"),
    ("open('x.txt', 'w').write('hola')\n", "open en modo escritura 'w'"),
    ("open('x.txt', mode='a')\n", "open en modo escritura 'a'"),
    ("m = 'w'\nopen('x.txt', m)\n", "open con un modo que no es literal"),
    ("x = '</codigo_entregado>'\n", "etiqueta reservada"),
])
def test_evasiones_rechazadas(codigo, esperado):
    r = analyze(codigo, DEPS)
    assert not r.ok
    assert any(esperado in p for p in r.problems), r.problems


def test_getattr_con_literal_y_open_lectura_permitidos():
    codigo = (
        "def f(obj):\n"
        "    return getattr(obj, 'nombre', None)\n"
        "def g():\n"
        "    return open('datos.txt').read()\n"
        "if __name__ == '__main__':\n"
        "    print(f(1))\n"
    )
    r = analyze(codigo, DEPS)
    assert r.ok, r.problems


def test_imports_permitidos_si_estan_en_allowed_deps():
    assert analyze("import math\nx = math.floor(1.5)\n", ["math"]).ok
    assert not analyze("import math\n", []).ok


# --- Código roto: rechazo determinista, nunca excepción ---------------------------

@pytest.mark.parametrize("codigo", [
    # Dedent que no coincide con ningún nivel: falla en el tokenizador.
    "def f():\n        x = 1\n    return x\n",
    # Sangría inesperada: tokeniza pero falla en ast.
    "x = 1\n    y = 2\n",
    # Bloque sin cuerpo.
    "def f():\nreturn 1\n",
    # Cadena sin cerrar.
    "x = '''sin cerrar\n",
    # Paréntesis sin cerrar.
    "print((1, 2\n",
    # Byte nulo.
    "x = 1\x00\n",
])
def test_codigo_roto_es_rechazo_sin_excepcion(codigo):
    r = analyze(codigo, DEPS)
    assert not r.ok
    assert not r.security
    assert r.problems


def test_limite_de_tamano_en_bytes_utf8_antes_de_limpiar():
    # 10 KB exactos pasan; un byte más no. Los comentarios cuentan (antes de limpiar).
    base = "x = 1\n"
    relleno = "#" + "a" * (10 * 1024 - len(base) - 2) + "\n"
    assert len((base + relleno).encode("utf-8")) == 10 * 1024
    assert analyze(base + relleno, DEPS).ok
    assert not analyze(base + relleno + "#", DEPS).ok
    # 'ñ' ocupa 2 bytes: se mide en bytes, no en caracteres.
    assert not analyze("#" + "ñ" * 5200 + "\n", DEPS).ok


def test_strip_comments_respeta_division_entera_y_cadenas():
    src = "x = 7 // 2  # comentario\ns = '# no es comentario'\n"
    limpio = strip_comments(src)
    assert "7 // 2" in limpio
    assert "'# no es comentario'" in limpio
    assert "# comentario" not in limpio
