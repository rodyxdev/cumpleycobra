"""Capas 1 y 2 del Motor de Análisis Estático de Código basado en LLM.

Capa 1 (higiene): tamaño máximo y comentarios fuera con el tokenizador.
Capa 2 (determinista con ast): sintaxis, imports permitidos y llamadas prohibidas.

El servidor nunca ejecuta el código: esta capa protege al cliente que lo va a correr.
Cualquier error de tokenize/ast es un rechazo determinista, nunca un error 500.
"""

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

from .config import MAX_CODE_BYTES

RESERVED_TAG = "codigo_entregado"

FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "getenv", "subprocess", "socket",
    "globals", "vars", "breakpoint", "locals",
}
FORBIDDEN_ATTRS = {"system", "environ", "getenv", "putenv", "popen",
                   "write_text", "write_bytes"}
FORBIDDEN_ATTR_PREFIXES = ("exec", "spawn")
DYNAMIC_ATTR_FUNCS = {"getattr", "setattr", "delattr"}
ALLOWED_DUNDERS = {"__name__", "__main__", "__init__"}
DUNDER_RE = re.compile(r"^__\w+__$")
WRITE_MODE_CHARS = set("wax+")


@dataclass
class DeterministicResult:
    ok: bool
    clean_code: str = ""
    problems: list[str] = field(default_factory=list)
    security: bool = False  # True si el rechazo es por seguridad (no por sintaxis o tamaño)

    @property
    def reason(self) -> str:
        return "Rechazado por la capa determinista: " + "; ".join(self.problems)


def strip_comments(src: str) -> str:
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type != tokenize.COMMENT]
    return tokenize.untokenize(toks)


def _is_dunder(name: str) -> bool:
    return bool(DUNDER_RE.match(name)) and name not in ALLOWED_DUNDERS


class _Checker(ast.NodeVisitor):
    def __init__(self, allowed_deps: set[str]):
        self.allowed = allowed_deps
        self.problems: list[str] = []
        # Nodos Name ya validados como parte de una llamada permitida.
        self._ok_names: set[int] = set()

    def add(self, node: ast.AST, msg: str) -> None:
        line = getattr(node, "lineno", "?")
        self.problems.append(f"línea {line}: {msg}")

    # --- imports -----------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in self.allowed:
                self.add(node, f"import no permitido '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.add(node, "import relativo no permitido")
        else:
            top = (node.module or "").split(".")[0]
            if top not in self.allowed:
                self.add(node, f"import no permitido '{node.module}'")
        self.generic_visit(node)

    # --- llamadas con reglas especiales ------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in DYNAMIC_ATTR_FUNCS:
                if (len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    self._ok_names.add(id(func))
                else:
                    self.add(node, f"{func.id} con un nombre que no es literal")
                    self._ok_names.add(id(func))  # ya reportado
            elif func.id == "open":
                mode = None
                if len(node.args) >= 2:
                    mode = node.args[1]
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode = kw.value
                if mode is None:
                    self._ok_names.add(id(func))  # lectura por defecto
                elif isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                    if WRITE_MODE_CHARS & set(mode.value):
                        self.add(node, f"open en modo escritura '{mode.value}'")
                    self._ok_names.add(id(func))
                else:
                    self.add(node, "open con un modo que no es literal")
                    self._ok_names.add(id(func))
        self.generic_visit(node)

    # --- nombres y atributos -----------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if id(node) in self._ok_names:
            return
        if node.id in FORBIDDEN_NAMES:
            self.add(node, f"uso prohibido de '{node.id}'")
        elif node.id in DYNAMIC_ATTR_FUNCS or node.id == "open":
            self.add(node, f"uso de '{node.id}' fuera de una llamada verificable")
        elif _is_dunder(node.id):
            self.add(node, f"nombre reservado '{node.id}'")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr in FORBIDDEN_ATTRS or attr.startswith(FORBIDDEN_ATTR_PREFIXES):
            self.add(node, f"atributo prohibido '.{attr}'")
        elif _is_dunder(attr):
            self.add(node, f"atributo reservado '.{attr}'")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _is_dunder(node.value):
            self.add(node, f"texto con nombre reservado '{node.value}'")

    # --- definiciones con nombres reservados -------------------------------
    def _check_def_name(self, node, name: str) -> None:
        if _is_dunder(name):
            self.add(node, f"nombre reservado '{name}'")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_def_name(node, node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_def_name(node, node.name)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self._check_def_name(node, node.arg)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg:
            self._check_def_name(node, node.arg)
        self.generic_visit(node)


def analyze(code: str, allowed_deps: list[str]) -> DeterministicResult:
    """Capas 1 y 2. Devuelve el código limpio si pasa, o la lista de problemas."""
    # Capa 1: tamaño en bytes UTF-8, antes de limpiar.
    size = len(code.encode("utf-8"))
    if size > MAX_CODE_BYTES:
        return DeterministicResult(False, problems=[
            f"el código pesa {size} bytes y el máximo es {MAX_CODE_BYTES}"])

    # La etiqueta que delimita el código ante Gemini no puede aparecer dentro de él.
    if RESERVED_TAG in code:
        return DeterministicResult(False, security=True, problems=[
            f"el código contiene la etiqueta reservada '{RESERVED_TAG}'"])

    # Capa 1: comentarios fuera con el tokenizador (nunca con regex).
    try:
        clean = strip_comments(code)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError) as exc:
        return DeterministicResult(False, problems=[f"el código no se puede tokenizar ({_short(exc)})"])

    # Capa 2: sintaxis.
    try:
        tree = ast.parse(clean)
    except (SyntaxError, ValueError) as exc:
        return DeterministicResult(False, problems=[f"error de sintaxis ({_short(exc)})"])

    checker = _Checker(set(allowed_deps))
    checker.visit(tree)
    if checker.problems:
        return DeterministicResult(False, clean_code=clean, problems=checker.problems, security=True)
    return DeterministicResult(True, clean_code=clean)


def _short(exc: Exception) -> str:
    if isinstance(exc, SyntaxError) and exc.lineno:
        return f"{exc.msg}, línea {exc.lineno}"
    return str(exc).split("\n")[0][:160]
