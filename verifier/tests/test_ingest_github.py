import os
import subprocess

import pytest

from verifier.ingest import GitHubPublicSource, IngestError, fetch_submission

GOOD_SHA = "0" * 40


@pytest.mark.parametrize(
    "repo,sha",
    [
        ("not-a-repo", GOOD_SHA),
        ("owner/../etc", GOOD_SHA),
        ("https://github.com/a/b", GOOD_SHA),
        ("owner/name;rm -rf", GOOD_SHA),
        ("owner/name", "abc123"),  # SHA corto: no se acepta, debe ser fijo y completo
        ("owner/name", "main"),
        ("owner/name", "g" * 40),
    ],
)
def test_invalid_repo_or_sha_rejected_before_network(repo, sha):
    with pytest.raises(IngestError):
        fetch_submission(GitHubPublicSource(repo=repo, sha=sha))



def _peeled_tag_sha(repo: str, tag: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/tags/{tag}^{{}}"],
            capture_output=True, text=True, timeout=30,
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out[0] if out else None


@pytest.mark.network
@pytest.mark.skipif(os.getenv("SKIP_NETWORK_TESTS") == "1", reason="SKIP_NETWORK_TESTS=1")
def test_public_repo_checkout_at_sha_is_deterministic():
    sha = _peeled_tag_sha("pallets/itsdangerous", "2.2.0")
    if sha is None:
        pytest.skip("sin acceso a github.com")
    src = GitHubPublicSource(repo="pallets/itsdangerous", sha=sha)
    a, b = fetch_submission(src), fetch_submission(src)
    assert a.content_hash == b.content_hash
    assert (a.path / "pyproject.toml").exists()
    assert not (a.path / ".git").exists()
    assert a.source == {"kind": "github_public", "repo": "pallets/itsdangerous", "sha": sha}
