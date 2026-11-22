import pytest

from verifier.ingest import IngestError, ZipSource, fetch_submission, hash_workspace
from verifier.ingest.zip_upload import safe_member_parts


def workspaces_left(tmp_path):
    root = tmp_path / "work" / "workspaces"
    return list(root.iterdir()) if root.exists() else []


def test_valid_zip_is_extracted_and_hashed(zip_factory, tmp_path):
    ws = fetch_submission(ZipSource(path=zip_factory({"a.txt": b"A", "dir/b.txt": b"B"})))
    assert (ws.path / "a.txt").read_bytes() == b"A"
    assert (ws.path / "dir" / "b.txt").read_bytes() == b"B"
    assert ws.content_hash == hash_workspace(ws.path)
    assert ws.source == {"kind": "zip"}  # no se expone la ruta local


def test_same_zip_content_same_hash(zip_factory):
    entries = {"a.txt": b"A", "dir/b.txt": b"B"}
    h1 = fetch_submission(ZipSource(path=zip_factory(entries))).content_hash
    h2 = fetch_submission(ZipSource(path=zip_factory(dict(reversed(list(entries.items())))))).content_hash
    assert h1 == h2


def test_single_top_level_dir_is_stripped(zip_factory):
    flat = fetch_submission(ZipSource(path=zip_factory({"a.txt": b"A", "d/b.txt": b"B"})))
    wrapped = fetch_submission(ZipSource(path=zip_factory({"repo-main/": b"", "repo-main/a.txt": b"A", "repo-main/d/b.txt": b"B"})))
    assert (wrapped.path / "a.txt").exists()
    assert flat.content_hash == wrapped.content_hash


@pytest.mark.parametrize(
    "evil",
    [
        "../evil.txt",
        "ok/../../evil.txt",
        "..\\evil.txt",
        "/etc/passwd",
        "\\windows\\evil.txt",
        "C:/evil.txt",
        "C:\\evil.txt",
        "file.txt:stream",
        "dir/CON.txt",
        "trailing. ",
    ],
)
def test_zip_slip_and_dangerous_names_rejected(zip_factory, tmp_path, evil):
    path = zip_factory({"good.txt": b"ok", evil: b"pwned"})
    with pytest.raises(IngestError):
        fetch_submission(ZipSource(path=path))
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "work" / "evil.txt").exists()
    assert workspaces_left(tmp_path) == []  # el workspace parcial se limpia


def test_safe_member_parts_accepts_normal_paths():
    assert safe_member_parts("src/./pkg/mod.py") == ("src", "pkg", "mod.py")
    assert safe_member_parts("src\\win\\style.py") == ("src", "win", "style.py")


def test_symlink_entries_rejected(zip_factory):
    path = zip_factory({"a.txt": b"A"}, symlinks={"link": "/etc/passwd"})
    with pytest.raises(IngestError, match="symlink"):
        fetch_submission(ZipSource(path=path))


def test_duplicate_entries_rejected(zip_factory):
    import zipfile

    path = zip_factory({"a.txt": b"1"})
    with pytest.warns(UserWarning), zipfile.ZipFile(path, "a") as zf:
        zf.writestr("A.TXT", b"2")  # mismo archivo en Windows
        zf.writestr("a.txt", b"3")
    with pytest.raises(IngestError, match="duplicada"):
        fetch_submission(ZipSource(path=path))


def test_uncompressed_size_limit_stops_zip_bomb(zip_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("ZIP_MAX_UNCOMPRESSED_BYTES", str(1024 * 1024))
    path = zip_factory({"bomb.bin": b"\0" * (5 * 1024 * 1024)})
    assert path.stat().st_size < 64 * 1024  # se comprime muchísimo
    with pytest.raises(IngestError, match="descomprimido"):
        fetch_submission(ZipSource(path=path))
    assert workspaces_left(tmp_path) == []


def test_too_many_files_rejected(zip_factory, monkeypatch):
    monkeypatch.setenv("ZIP_MAX_FILES", "3")
    path = zip_factory({f"f{i}.txt": b"x" for i in range(4)})
    with pytest.raises(IngestError, match="entradas"):
        fetch_submission(ZipSource(path=path))


def test_upload_size_limit(zip_factory, monkeypatch):
    monkeypatch.setenv("ZIP_MAX_UPLOAD_BYTES", "10")
    with pytest.raises(IngestError, match="supera"):
        fetch_submission(ZipSource(path=zip_factory({"a.txt": b"A"})))


def test_not_a_zip(tmp_path):
    bogus = tmp_path / "x.zip"
    bogus.write_bytes(b"esto no es un zip")
    with pytest.raises(IngestError, match="ZIP válido"):
        fetch_submission(ZipSource(path=bogus))
