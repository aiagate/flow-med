from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "verify-release-ref.sh"


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    subprocess.run(
        ["git", "-C", tmp_path, "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", tmp_path, "config", "user.name", "Test User"],
        check=True,
    )
    (tmp_path / "release.txt").write_text("release\n")
    subprocess.run(["git", "-C", tmp_path, "add", "release.txt"], check=True)
    subprocess.run(["git", "-C", tmp_path, "commit", "-qm", "release"], check=True)
    sha = subprocess.run(
        ["git", "-C", tmp_path, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tmp_path, sha


def verify(
    repository: Path, ref: str, ref_type: str, sha: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SCRIPT, ref, ref_type, sha],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


def test_accepts_exact_semver_tag_at_workflow_commit(
    repository: tuple[Path, str],
) -> None:
    path, sha = repository
    subprocess.run(["git", "-C", path, "tag", "v1.2.3"], check=True)

    result = verify(path, "refs/tags/v1.2.3", "tag", sha)

    assert result.returncode == 0
    assert "Verified production release v1.2.3" in result.stdout


@pytest.mark.parametrize(
    ("ref", "ref_type"),
    [
        ("refs/heads/main", "branch"),
        ("refs/tags/1.2.3", "tag"),
        ("refs/tags/v1.2", "tag"),
        ("refs/tags/v1.2.3rc1", "tag"),
        ("refs/tags/v1.2.3.4", "tag"),
        ("refs/tags/v01.2.3", "tag"),
    ],
)
def test_rejects_non_release_refs(
    repository: tuple[Path, str], ref: str, ref_type: str
) -> None:
    path, sha = repository

    result = verify(path, ref, ref_type, sha)

    assert result.returncode != 0


def test_rejects_tag_that_does_not_resolve_to_workflow_commit(
    repository: tuple[Path, str],
) -> None:
    path, release_sha = repository
    subprocess.run(["git", "-C", path, "tag", "v1.2.3"], check=True)
    (path / "release.txt").write_text("later\n")
    subprocess.run(["git", "-C", path, "commit", "-qam", "later"], check=True)
    later_sha = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = verify(path, "refs/tags/v1.2.3", "tag", later_sha)

    assert result.returncode != 0
    assert release_sha in result.stderr
