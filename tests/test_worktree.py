from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from guardedcoder.workspace.discard import discard_owned_worktree, discard_worktree
from guardedcoder.workspace.gitops import DirtyWorktreeError, assert_clean
from guardedcoder.workspace.worktree import (
    OwnershipError,
    create_task_worktree,
    load_ownership,
    ownership_record_path,
)


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


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "origin"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    return repo, _commit(repo, "base")


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_assert_clean_rejects_dirty_tree_without_altering_content(
    tmp_path: Path, dirty_kind: str
) -> None:
    repo, base_commit = _repo(tmp_path)
    dirty_path = repo / ("tracked.txt" if dirty_kind == "tracked" else "untracked.txt")
    dirty_path.write_text(f"{dirty_kind} user content\n", encoding="utf-8")
    status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(DirtyWorktreeError):
        assert_clean(repo)

    assert dirty_path.read_text(encoding="utf-8") == f"{dirty_kind} user content\n"
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "stash", "list") == ""


def test_create_task_worktree_uses_fixed_base_and_records_ownership(
    tmp_path: Path,
) -> None:
    repo, base_commit = _repo(tmp_path)
    (repo / "tracked.txt").write_text("new tip\n", encoding="utf-8")
    tip_commit = _commit(repo, "tip")
    harness = tmp_path / "harness"

    ownership = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )

    assert ownership.task_id == "task-31"
    assert ownership.repo_real_path == repo.resolve()
    assert ownership.base_commit == base_commit
    assert ownership.worktree_path.parent == (harness / "worktrees").resolve()
    assert ownership.worktree_path != repo.resolve()
    assert _git(ownership.worktree_path, "rev-parse", "HEAD") == base_commit
    assert (
        ownership.worktree_path / "tracked.txt"
    ).read_text(encoding="utf-8") == "base\n"
    assert _git(repo, "rev-parse", "HEAD") == tip_commit
    assert load_ownership("task-31", harness_dir=harness) == ownership


@pytest.mark.parametrize(
    "task_id",
    ["../escape", ".", "a/b", "", "foo.", "NUL", "CON", "aux", "com1", "NUL.txt"],
)
def test_create_rejects_task_ids_that_could_escape_registry(
    tmp_path: Path, task_id: str
) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"

    with pytest.raises(ValueError):
        create_task_worktree(
            task_id=task_id,
            repo_path=repo,
            base_commit=base_commit,
            harness_dir=harness,
        )

    assert not (harness / "worktrees").exists()


def test_create_rejects_harness_directory_inside_origin_repo(tmp_path: Path) -> None:
    repo, base_commit = _repo(tmp_path)

    with pytest.raises(OwnershipError):
        create_task_worktree(
            task_id="task-31",
            repo_path=repo,
            base_commit=base_commit,
            harness_dir=repo / ".guardedcoder",
        )

    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_discard_removes_only_the_recorded_owned_worktree(tmp_path: Path) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    (ownership.worktree_path / "user-change.txt").write_text(
        "discard me\n", encoding="utf-8"
    )

    discard_worktree(
        "task-31", ownership.worktree_path, harness_dir=harness
    )

    assert not ownership.worktree_path.exists()
    assert not ownership_record_path("task-31", harness_dir=harness).exists()
    assert repo.exists()
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_discard_refuses_wrong_parent_origin_and_other_task_paths(
    tmp_path: Path,
) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"
    owned = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    other = create_task_worktree(
        task_id="other-task",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep\n", encoding="utf-8")

    untrusted_paths = [
        unrelated,
        owned.worktree_path.parent,
        repo,
        other.worktree_path,
    ]
    for requested_path in untrusted_paths:
        with pytest.raises(OwnershipError):
            discard_worktree(
                "task-31", requested_path, harness_dir=harness
            )
        assert owned.worktree_path.exists()
        assert other.worktree_path.exists()
        assert repo.exists()
        assert unrelated.exists()


def test_discard_refuses_tampered_ownership_record_without_deleting(
    tmp_path: Path,
) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    record_path = ownership_record_path("task-31", harness_dir=harness)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["base_commit"] = "0" * 40
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(OwnershipError):
        discard_worktree(
            "task-31", ownership.worktree_path, harness_dir=harness
        )

    assert ownership.worktree_path.exists()
    assert repo.exists()


def test_discard_refuses_symlink_or_junction_alias_before_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    monkeypatch.setattr(
        "guardedcoder.workspace.discard._path_is_alias",
        lambda path: path == ownership.worktree_path,
    )

    with pytest.raises(OwnershipError, match="symlink or junction"):
        discard_owned_worktree("task-31", harness_dir=harness)

    assert ownership.worktree_path.exists()
    assert ownership_record_path("task-31", harness_dir=harness).exists()
    assert repo.exists()


def test_discard_owned_worktree_cleans_after_head_moves(tmp_path: Path) -> None:
    repo, base_commit = _repo(tmp_path)
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-31",
        repo_path=repo,
        base_commit=base_commit,
        harness_dir=harness,
    )
    (ownership.worktree_path / "later.txt").write_text("later\n", encoding="utf-8")
    moved = _commit(ownership.worktree_path, "later")
    assert moved != base_commit

    discarded = discard_owned_worktree("task-31", harness_dir=harness)

    assert discarded.worktree_path == ownership.worktree_path
    assert not ownership.worktree_path.exists()
    assert not ownership_record_path("task-31", harness_dir=harness).exists()
    assert repo.exists()
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"
