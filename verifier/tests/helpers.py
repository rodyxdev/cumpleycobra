from pathlib import Path

from verifier.contract import ExecutionSpec, Interface, InterfaceSymbol
from verifier.sandbox import docker_available

import pytest

requires_docker = pytest.mark.skipif(not docker_available(), reason="Docker no está disponible")


def write_files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return root


def script_spec(module: str, names: list[str], allowed: list[str] | None = None) -> ExecutionSpec:
    symbols = [InterfaceSymbol(module=module, name=n, kind="function", signature=f"{n}()") for n in names]
    return ExecutionSpec(profile="script", interface=Interface(symbols=symbols), allowed_dependencies=allowed or [])
