from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

from guardedcoder.workspace.artifact import GitPatchArtifactPort
from guardedcoder.workspace.worktree import create_task_worktree


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=GuardedCoder Tests",
            "-c",
            "user.email=guardedcoder-tests@example.invalid",
            "commit",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def _task_repo(tmp_path: Path) -> tuple[Path, object]:
    repo = tmp_path / "origin"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-32",
        repo_path=repo,
        base_commit=base,
        harness_dir=harness,
    )
    return repo, SimpleNamespace(
        task_id="task-32",
        worktree_identity=str(ownership.worktree_path),
        base_commit=base,
        max_patch_bytes=1_000_000,
    )


def test_export_writes_complete_diff_including_untracked(tmp_path: Path) -> None:
    repo, task = _task_repo(tmp_path)
    worktree = Path(task.worktree_identity)
    (worktree / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (worktree / "new.txt").write_text("untracked\n", encoding="utf-8")
    cached_before = _git(worktree, "diff", "--cached")
    status_before = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all")

    artifact = GitPatchArtifactPort(artifact_dir=tmp_path / "artifacts").export(task)

    assert artifact.over_limit is False
    assert artifact.can_mark_patch_ready is True
    assert artifact.path.read_bytes() == artifact.body
    assert artifact.sha256 == hashlib.sha256(artifact.body).hexdigest()
    assert b"changed" in artifact.body
    assert b"untracked" in artifact.body
    assert _git(worktree, "diff", "--cached") == cached_before
    assert _git(worktree, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_over_limit_keeps_full_body_and_blocks_patch_ready(tmp_path: Path) -> None:
    _repo, task = _task_repo(tmp_path)
    worktree = Path(task.worktree_identity)
    payload = ("x" * 4000 + "\n").encode("utf-8")
    (worktree / "big.txt").write_bytes(payload)
    task.max_patch_bytes = 64

    artifact = GitPatchArtifactPort(artifact_dir=tmp_path / "artifacts").export(task)

    assert len(artifact.body) > 64
    assert artifact.body == artifact.path.read_bytes()
    assert payload in artifact.body
    assert artifact.over_limit is True
    assert artifact.can_mark_patch_ready is False
    assert artifact.sha256 == hashlib.sha256(artifact.body).hexdigest()


def test_summary_may_truncate_but_includes_sha256_and_path(tmp_path: Path) -> None:
    _repo, task = _task_repo(tmp_path)
    worktree = Path(task.worktree_identity)
    (worktree / "tracked.txt").write_text("changed line for summary\n", encoding="utf-8")
    artifact = GitPatchArtifactPort(artifact_dir=tmp_path / "artifacts").export(task)

    text = artifact.summary(max_bytes=40)
    assert artifact.sha256 in text
    assert str(artifact.path) in text
    assert "truncated=true" in text
