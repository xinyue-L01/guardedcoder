from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"
GITLAB_YML = ROOT / ".gitlab-ci.yml"
_UNIT_TEST_JOB = re.compile(r"(?m)^unit-test:\s*$")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(ROOT).as_posix()}"
    return path.read_text(encoding="utf-8")


def test_required_ci_files_exist_with_unit_test_secret_scan_and_hashed_lock() -> None:
    ci = _read(CI_YML)
    release = _read(RELEASE_YML)
    gitlab = _read(GITLAB_YML)

    assert _UNIT_TEST_JOB.search(gitlab)
    assert "secret_scan" in ci
    assert "--require-hashes" in ci
    assert "--require-hashes" in release
    assert "--require-hashes" in gitlab
    assert "requirements-dev.txt" in ci
    assert "requirements-dev.txt" in release
    assert "requirements-dev.txt" in gitlab


def test_hashed_lock_contains_linux_keyring_backend() -> None:
    lock = _read(ROOT / "requirements-dev.txt")
    assert "secretstorage==" in lock.lower()


def test_github_push_pr_ci_uses_python_312_hashed_lock_pytest_scan_and_wheel() -> None:
    text = _read(CI_YML)
    lowered = text.lower()

    assert "pull_request" in text
    assert "3.12" in text
    assert "--require-hashes" in text
    assert "requirements-dev.txt" in text
    assert "secret_scan" in text
    assert "python -m pytest" in text
    assert "python -m build --wheel" in text
    assert "permissions:" in text
    assert "contents: read" in text
    assert "pypi" not in lowered
    assert "twine" not in lowered
    assert "gh-action-pypi-publish" not in lowered
    assert "action-gh-release" not in lowered


def test_github_tag_release_builds_wheel_sha256_and_uploads_assets() -> None:
    text = _read(RELEASE_YML)
    lowered = text.lower()

    assert "tags" in text
    assert "pull_request" not in text
    assert "branches:" not in text
    assert "3.12" in text
    assert "--require-hashes" in text
    assert "python -m build --wheel" in text
    assert "hashlib.sha256" in text
    assert "read_bytes" in text
    assert "*.whl" in text
    assert "action-gh-release" in lowered or "gh release create" in lowered
    assert "contents: write" in text
    assert "pypi" not in lowered
    assert "twine" not in lowered


def test_gitlab_unit_test_job_installs_from_lock_and_runs_pytest() -> None:
    text = _read(GITLAB_YML)

    assert _UNIT_TEST_JOB.search(text)
    assert "3.12" in text
    assert "--require-hashes" in text
    assert "requirements-dev.txt" in text
    assert "python -m pytest" in text
