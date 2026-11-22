"""Señales deterministas sobre una entrega de varios archivos (fase 3, portado de v2).

- inyección: texto en comentarios o strings dirigido al evaluador automático;
- trampa: la entrada o la salida de un ejemplo público incrustada en el código;
- manipulación: hooks de pytest, inspección de la pila, `os._exit`, referencias a la suite.

Las señales no deciden solas: se reportan al juez y cualquiera de ellas impide aprobar. Nunca se
ejecuta el código. Se escanean todos los `.py` de la entrega, también los tests propios del
programador (que nunca se ejecutan).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass


@dataclass
class SourceFile:
    rel: str
    text: str
    tree: ast.Module | None
    syntax_error: str | None = None


@dataclass(frozen=True)
class Signal:
    kind: str      # injection | cheating | tampering
    file: str
    line: int
    snippet: str
    detail: str

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"


def load_sources(files: dict[str, str]) -> list[SourceFile]:
    sources = []
    for rel, text in sorted(files.items()):
        if not rel.endswith(".py"):
            continue
        try:
            sources.append(SourceFile(rel, text, ast.parse(text, filename=rel)))
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            sources.append(SourceFile(rel, text, None, f"{rel}: {str(exc)[:160]}"))
    return sources


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Nombre local → nombre completo (`import os as o` → o: os; `from os import system` → system: os.system)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def _resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    full = aliases.get(head, head)
    return f"{full}.{rest}" if rest else full


def imported_modules(src: SourceFile) -> list[tuple[str, int]]:
    """(módulo absoluto, línea) de cada import, incluido `__import__`/`importlib.import_module` con literal."""
    found = []
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.module, node.lineno))
        elif isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn in ("__import__", "importlib.import_module") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((arg.value, node.lineno))
    return found


def _line(src: SourceFile, lineno: int) -> str:
    lines = src.text.splitlines()
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ia|ai|llm|gpt|chatgpt|claude|llama|muse|gemini|modelo|model|asistente|assistant|evaluador|evaluator"
        r"|juez|judge|grader|revisor|reviewer|verificador|verifier)\b[^\n]{0,80}"
        r"\b(apru[eé]b\w*|aprob\w*|approv\w*|pass|marc\w*|mark|calific\w*|grade|ignor\w*|acept\w*|accept\w*)",
        r"\b(ignore|disregard|forget)\b[^\n]{0,30}\b(previous|prior|above|all|earlier)\b[^\n]{0,20}\b(instructions?|rules?)",
        r"\b(ignora|olvida|omite)\b[^\n]{0,30}\b(instrucciones|reglas|criterios)",
        r"\b(system prompt|prompt del sistema|jailbreak)\b",
        r"\b(verdict|veredicto)\b[^\n]{0,40}\b(pass|aprobad|approved|aprueba)",
        r"\b(test_defect|todos los criterios (se )?cumplen|all criteria (are )?(met|satisfied))\b",
    )
]

_TAMPER_NAMES = {
    "sys._getframe": "inspecciona frames de la pila",
    "inspect.stack": "inspecciona la pila de llamadas",
    "inspect.currentframe": "inspecciona frames de la pila",
    "sys.settrace": "instala un tracer",
    "sys.setprofile": "instala un profiler",
    "os._exit": "termina el proceso saltándose pytest",
    "gc.get_objects": "recorre objetos del intérprete",
    "gc.get_referrers": "recorre objetos del intérprete",
    "atexit.register": "registra código al salir del intérprete",
}
_TAMPER_MODULES = {"pytest", "_pytest", "pluggy", "unittest.mock", "junitparser", "cc_channel", "cc_codec"}
_TAMPER_STRINGS = ("/hidden", "junit", "/out/", "conftest", "PYTEST_CURRENT_TEST", "/cc/")


def _comments_and_strings(src: SourceFile) -> list[tuple[int, str]]:
    found = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src.text).readline):
            if tok.type == tokenize.COMMENT:
                found.append((tok.start[0], tok.string))
    except (tokenize.TokenError, SyntaxError):
        pass
    if src.tree is not None:
        for node in ast.walk(src.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((node.lineno, node.value))
    return found


def scan_text_for_injection(text: str) -> str | None:
    """Fragmento que parece dirigido al evaluador, o None."""
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)[:160]
    return None


def _injection_signals(src: SourceFile) -> list[Signal]:
    signals = []
    for lineno, text in _comments_and_strings(src):
        hit = scan_text_for_injection(text)
        if hit:
            signals.append(Signal("injection", src.rel, lineno, hit, "texto dirigido al evaluador automático"))
    return signals


def _tamper_signals(src: SourceFile) -> list[Signal]:
    if src.tree is None:
        return []
    signals = []
    aliases = _alias_map(src.tree)
    for module, line in imported_modules(src):
        if any(module == m or module.startswith(m + ".") for m in _TAMPER_MODULES):
            signals.append(Signal("tampering", src.rel, line, _line(src, line), f"importa {module} desde el código entregado"))
    for node in ast.walk(src.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("pytest_"):
            signals.append(Signal("tampering", src.rel, node.lineno, _line(src, node.lineno),
                                  f"define un hook de pytest ({node.name})"))
        name = _dotted(node.func) if isinstance(node, ast.Call) else None
        if name:
            full = _resolve(name, aliases)
            if full in _TAMPER_NAMES:
                signals.append(Signal("tampering", src.rel, node.lineno, _line(src, node.lineno), _TAMPER_NAMES[full]))
        if isinstance(node, (ast.Name, ast.Attribute)) and _dotted(node) in ("__builtins__", "builtins.__dict__"):
            signals.append(Signal("tampering", src.rel, node.lineno, _line(src, node.lineno), "manipula builtins"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for needle in _TAMPER_STRINGS:
                if needle in node.value:
                    signals.append(Signal("tampering", src.rel, node.lineno, _line(src, node.lineno),
                                          f"referencia a la infraestructura de test ({needle})"))
                    break
    return signals


def parse_call_example(text: str) -> tuple[str, list, dict]:
    """`f("a", n=2)` → ("f", ["a"], {"n": 2}). Solo literales; si no, ValueError."""
    node = ast.parse(text.strip(), mode="eval").body
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise ValueError("debe ser una llamada simple: nombre(args)")
    args = [ast.literal_eval(a) for a in node.args]
    kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg}
    return node.func.id, args, kwargs


def _example_literals(examples: list[dict]) -> tuple[set[str], list[object]]:
    """Strings de entrada (≥ 6 caracteres) y salidas esperadas de los ejemplos públicos de v1
    (`{"input": "f(...)", "output": "<literal de Python>"}`)."""
    inputs: set[str] = set()
    outputs: list[object] = []
    for ex in examples:
        try:
            _, args, kwargs = parse_call_example(ex["input"])
            value = ast.literal_eval(ex["output"].strip())
        except (ValueError, SyntaxError, TypeError, KeyError, RecursionError, MemoryError):
            continue
        inputs |= {a for a in [*args, *kwargs.values()] if isinstance(a, str) and len(a) >= 6}
        if value not in (None, True, False, 0, "", {}, []):
            outputs.append(value)
    return inputs, outputs


def _cheating_signals(src: SourceFile, examples: list[dict]) -> list[Signal]:
    if src.tree is None:
        return []
    inputs, outputs = _example_literals(examples)
    signals = []
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in inputs:
            signals.append(Signal("cheating", src.rel, node.lineno, _line(src, node.lineno),
                                  "contiene literalmente la entrada de un ejemplo público"))
        elif isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)) and outputs:
            try:
                value = ast.literal_eval(node)
            except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
                continue
            if value in outputs:
                signals.append(Signal("cheating", src.rel, node.lineno, _line(src, node.lineno),
                                      "contiene literalmente la salida esperada de un ejemplo público"))
    return signals


def output_signals(outcomes: list[dict]) -> list[Signal]:
    """Inyección en lo que la entrega devolvió (mensajes de excepción, valores) y llegó a los tests."""
    signals = []
    for o in outcomes:
        hit = scan_text_for_injection(o.get("message", ""))
        if hit:
            signals.append(Signal("injection", o["nodeid"], 0, hit, "texto dirigido al evaluador en la salida de la entrega"))
    return signals


def collect_signals(sources: list[SourceFile], examples: list[dict]) -> list[Signal]:
    signals = []
    for src in sources:
        try:
            signals += _injection_signals(src) + _tamper_signals(src) + _cheating_signals(src, examples)
        except (RecursionError, MemoryError):
            signals.append(Signal("tampering", src.rel, 0, "", "código anidado demasiado hondo para revisarlo"))
    unique = {(s.kind, s.file, s.line, s.detail): s for s in signals}
    return sorted(unique.values(), key=lambda s: (s.file, s.line, s.kind))
