import io
import zipfile

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "network: necesita internet (PyPI o github.com)")


@pytest.fixture(autouse=True)
def _isolated_work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFIER_WORK_DIR", str(tmp_path / "work"))
    # Runtime de los contenedores: el por defecto (runc) salvo que se pida otro a propósito, p. ej.
    # en la VM: CYC_TEST_RUNTIME=runsc (gVisor).
    runtime = __import__("os").environ.get("CYC_TEST_RUNTIME")
    if runtime:
        monkeypatch.setenv("SANDBOX_RUNTIME", runtime)
    else:
        monkeypatch.delenv("SANDBOX_RUNTIME", raising=False)


def make_zip(entries: dict[str, bytes], *, symlinks: dict[str, str] | None = None) -> bytes:
    """ZIP en memoria. `entries` admite nombres arbitrarios (incluidos maliciosos)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            # ZipInfo explícito para que zipfile no "arregle" nombres maliciosos.
            zf.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3  # Unix
            info.external_attr = (0o120777 << 16)  # S_IFLNK
            zf.writestr(info, target)
    return buf.getvalue()


@pytest.fixture
def zip_factory(tmp_path):
    counter = iter(range(10_000))

    def _make(entries, **kw):
        path = tmp_path / f"upload-{next(counter)}.zip"
        path.write_bytes(make_zip(entries, **kw))
        return path

    return _make
