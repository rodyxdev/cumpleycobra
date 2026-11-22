"""Higiene del perfil web (portada de v2 `backend/web/verify.py`).

- Sitio estático: index.html en la raíz.
- Proyecto Node: package.json con package-lock.json; dependencias solo de las permitidas por el
  acuerdo; cada paquete del lockfile resuelto desde registry.npmjs.org con `integrity`; sin
  .npmrc ni configuración de registro; sin node_modules/ (se instala en el BUILD).
"""

from __future__ import annotations

import json
from pathlib import Path

from verifier.ingest.hashing import iter_entries
from verifier.verification.hygiene import HygieneReport

BLOCKED = {".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs"}
REGISTRY = "https://registry.npmjs.org/"
MAX_FILES = 2000


def check_web_hygiene(workspace: Path, allowed_dependencies: list[str]) -> HygieneReport:
    report = HygieneReport()
    entries = iter_entries(workspace)
    if len(entries) > MAX_FILES:
        report.blockers.append(f"la entrega tiene más de {MAX_FILES} archivos")
        return report
    names = {rel for rel, _, _ in entries}
    for rel, kind, _ in entries:
        if kind == "l":
            report.blockers.append(f"{rel}: enlace simbólico")
        if rel.rsplit("/", 1)[-1] in BLOCKED:
            report.blockers.append(f"{rel}: configuración de registro o de paquetes no permitida")
        if rel.startswith("node_modules/"):
            report.blockers.append("node_modules/ no se acepta: las dependencias se instalan en el BUILD")
            break
    if "package.json" not in names:
        if "index.html" not in names:
            report.blockers.append("falta index.html en la raíz (o un package.json con build)")
        return report
    if "package-lock.json" not in names:
        report.blockers.append("package.json sin package-lock.json: npm ci necesita el lockfile")
        return report
    allowed = {d.lower() for d in allowed_dependencies}
    try:
        pkg = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((workspace / "package-lock.json").read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        report.blockers.append(f"package.json o package-lock.json inválidos: {str(exc)[:200]}")
        return report
    if not isinstance(pkg, dict) or not isinstance(lock, dict):
        report.blockers.append("package.json o package-lock.json no son objetos JSON")
        return report
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name in (pkg.get(section) or {}):
            if name.lower() not in allowed:
                report.blockers.append(f"package.json: dependencia no permitida por el acuerdo: {name}")
    for path, meta in (lock.get("packages") or {}).items():
        if not path or not isinstance(meta, dict) or meta.get("link"):
            continue
        resolved, integrity = meta.get("resolved", ""), meta.get("integrity", "")
        if not str(resolved).startswith(REGISTRY) or not integrity:
            report.blockers.append(f"package-lock.json: {path} no viene de {REGISTRY} con integridad")
            break
    scripts = pkg.get("scripts") or {}
    lifecycle = sorted(k for k in scripts if k in ("preinstall", "install", "postinstall", "prepare"))
    if lifecycle:
        report.warnings.append("scripts de instalación que corren en el BUILD (aislado, sin tests ni secretos): "
                               + ", ".join(lifecycle))
    return report
