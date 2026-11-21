"""Capa 1 — higiene: archivos prohibidos, tamaño y dependencias fuera de las permitidas."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from verifier.contract import ExecutionSpec
from verifier.contract import normalize_dist_name
from verifier.ingest.hashing import iter_entries

# Bloqueantes: se cargan solos al arrancar Python o son código nativo que no podemos revisar.
_BLOCKED_NAMES = {"sitecustomize.py", "usercustomize.py"}
_BLOCKED_SUFFIXES = {".pth", ".so", ".pyd", ".dll", ".dylib", ".exe", ".pyc"}
# Advertencias: nuestra infraestructura ya los neutraliza (rootdir y sys.path propios),
# pero no tienen nada que hacer en una entrega y suelen indicar un intento de manipulación.
_SUSPICIOUS_NAMES = {"conftest.py", "pytest.ini"}
_SHADOW_MODULES = {"pytest", "_pytest", "pluggy", "iniconfig", "pytest_timeout", "httpx", "httpcore", "anyio"}

_REQ_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<extras>\[[^\]]*\])?\s*(?P<spec>(?:[<>=!~]=?|===)[^;]*)?\s*(?P<marker>;.*)?$"
)
MAX_FILES = 2000


@dataclass
class HygieneReport:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)  # validadas, listas para el BUILD

    @property
    def ok(self) -> bool:
        return not self.blockers


def _declared_requirements(workspace: Path, report: HygieneReport) -> list[tuple[str, str]]:
    """Devuelve (origen, línea) de requirements.txt y de [project].dependencies de pyproject.toml."""
    found: list[tuple[str, str]] = []
    req = workspace / "requirements.txt"
    if req.is_file():
        for raw in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split(" #", 1)[0].strip()
            if line and not line.startswith("#"):
                found.append(("requirements.txt", line))
    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            report.blockers.append(f"pyproject.toml inválido: {exc}")
            return found
        for line in data.get("project", {}).get("dependencies", []) or []:
            found.append(("pyproject.toml", str(line).strip()))
        if data.get("build-system"):
            report.warnings.append("pyproject.toml declara build-system: se ignora (no se construye el proyecto)")
    return found


def check_dependencies(workspace: Path, spec: ExecutionSpec, report: HygieneReport) -> None:
    allowed = {normalize_dist_name(d) for d in spec.allowed_dependencies}
    seen: set[str] = set()
    for origin, line in _declared_requirements(workspace, report):
        if line.startswith(("-", ".", "/")) or "://" in line or " @ " in line or line.startswith("git+"):
            report.blockers.append(f"{origin}: línea no permitida (opciones, URLs o rutas): {line!r}")
            continue
        match = _REQ_LINE.match(line)
        if not match:
            report.blockers.append(f"{origin}: requisito no reconocido: {line!r}")
            continue
        name = normalize_dist_name(match["name"])
        if name not in allowed:
            report.blockers.append(f"{origin}: dependencia no permitida por el contrato: {match['name']}")
            continue
        if match["extras"]:
            report.blockers.append(f"{origin}: extras no permitidos ({line!r}): instalarían dependencias no declaradas")
            continue
        if name in seen:
            continue
        seen.add(name)
        report.requirements.append(f"{name}{(match['spec'] or '').strip()}{(match['marker'] or '').strip()}")


def check_hygiene(workspace: Path, spec: ExecutionSpec) -> HygieneReport:
    report = HygieneReport()
    entries = iter_entries(workspace)
    if len(entries) > MAX_FILES:
        report.blockers.append(f"demasiados archivos ({len(entries)} > {MAX_FILES})")
    for rel, kind, _digest in entries:
        name = rel.rsplit("/", 1)[-1]
        suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        top = rel.split("/", 1)[0]
        if kind == "l":
            report.blockers.append(f"{rel}: enlace simbólico")
        if name.lower() in _BLOCKED_NAMES or suffix in _BLOCKED_SUFFIXES:
            report.blockers.append(f"{rel}: archivo prohibido (se carga automáticamente o es binario)")
        elif name.lower() in _SUSPICIOUS_NAMES:
            report.warnings.append(f"{rel}: archivo de configuración de pytest en la entrega (se ignora)")
        top_module = top.removesuffix(".py")
        if top_module in _SHADOW_MODULES and (top.endswith(".py") or "/" in rel):
            report.warnings.append(f"{rel}: nombre que coincide con la infraestructura de test ({top_module})")
    check_dependencies(workspace, spec, report)
    return report
