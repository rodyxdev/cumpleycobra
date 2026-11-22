import pytest

from verifier.verification.hygiene import check_hygiene

from .helpers import script_spec, write_files

GOOD = "def aplicar_descuento(precios, porcentaje):\n    return [round(p * (1 - porcentaje / 100), 2) for p in precios]\n"


def spec(allowed=None):
    return script_spec("descuentos", ["aplicar_descuento"], allowed)


def test_clean_submission_passes_hygiene(tmp_path):
    report = check_hygiene(write_files(tmp_path, {"descuentos.py": GOOD}), spec())
    assert report.ok and report.warnings == [] and report.requirements == []


@pytest.mark.parametrize("name", ["sitecustomize.py", "usercustomize.py", "evil.pth", "lib/_x.so", "m.pyd", "a.pyc"])
def test_forbidden_files_block(tmp_path, name):
    report = check_hygiene(write_files(tmp_path, {"descuentos.py": GOOD, name: "x"}), spec())
    assert not report.ok


@pytest.mark.parametrize("name", ["conftest.py", "pytest.ini", "pytest.py", "_pytest/__init__.py"])
def test_test_infra_files_warn(tmp_path, name):
    report = check_hygiene(write_files(tmp_path, {"descuentos.py": GOOD, name: "x"}), spec())
    assert report.ok and report.warnings


def test_dependencies_must_be_allowed(tmp_path):
    ws = write_files(tmp_path, {"descuentos.py": GOOD, "requirements.txt": "requests>=2.31  # http\n\nnumpy\n"})
    report = check_hygiene(ws, spec(["Requests"]))
    assert report.requirements == ["requests>=2.31"]
    assert any("numpy" in b for b in report.blockers)


@pytest.mark.parametrize("line", [
    "-e .", "--index-url https://evil", "git+https://github.com/x/y", "requests @ https://evil/x.whl",
    "./local", "/abs/path", "requests[socks]",
])
def test_dangerous_requirement_lines_block(tmp_path, line):
    ws = write_files(tmp_path, {"descuentos.py": GOOD, "requirements.txt": line})
    assert not check_hygiene(ws, spec(["requests"])).ok


def test_pyproject_dependencies_are_read(tmp_path):
    pyproject = '[project]\nname = "x"\ndependencies = ["requests==2.32.0"]\n[build-system]\nrequires = []\n'
    report = check_hygiene(write_files(tmp_path, {"descuentos.py": GOOD, "pyproject.toml": pyproject}), spec(["requests"]))
    assert report.ok and report.requirements == ["requests==2.32.0"]
    assert any("build-system" in w for w in report.warnings)


def test_symlinks_block(tmp_path):
    ws = write_files(tmp_path / "ws", {"descuentos.py": GOOD})
    try:
        (ws / "enlace").symlink_to("/etc/passwd")
    except OSError:
        pytest.skip("este sistema no permite crear symlinks")
    assert not check_hygiene(ws, spec()).ok
