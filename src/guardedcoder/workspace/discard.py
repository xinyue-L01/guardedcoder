from __future__ import annotations

import os
from pathlib import Path

from guardedcoder.workspace.gitops import GitOperationError, git_text, repo_real_path
from guardedcoder.workspace.worktree import (
    OwnershipError,
    WorktreeOwnership,
    load_ownership,
    ownership_record_path,
)


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _git_path(repo: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _verify_ownership(ownership: WorktreeOwnership) -> None:
    try:
        origin = repo_real_path(ownership.repo_real_path)
        if origin != ownership.repo_real_path.resolve():
            raise OwnershipError("origin repository ownership does not match")
        if not ownership.worktree_path.is_dir():
            raise OwnershipError("recorded worktree does not exist")

        worktree_root = repo_real_path(ownership.worktree_path)
        if worktree_root != ownership.worktree_path.resolve():
            raise OwnershipError("recorded path is not the worktree root")
        if worktree_root == origin:
            raise OwnershipError("recorded worktree aliases the origin repository")

        origin_common = _git_path(
            origin, git_text(origin, "rev-parse", "--git-common-dir")
        )
        worktree_common = _git_path(
            worktree_root,
            git_text(worktree_root, "rev-parse", "--git-common-dir"),
        )
        if origin_common != worktree_common:
            raise OwnershipError("worktree belongs to another repository")

        canonical_base = git_text(
            origin,
            "rev-parse",
            "--verify",
            f"{ownership.base_commit}^{{commit}}",
        ).lower()
        if canonical_base != ownership.base_commit:
            raise OwnershipError("origin no longer recognizes the recorded base commit")
    except GitOperationError as exc:
        raise OwnershipError("unable to verify worktree ownership") from exc


def discard_worktree(
    task_id: str,
    requested_path: str | Path,
    *,
    harness_dir: str | Path,
) -> WorktreeOwnership:
    """Discard only the exact worktree bound to task_id."""
    ownership = load_ownership(task_id, harness_dir=harness_dir)
    if _absolute(requested_path) != ownership.worktree_path:
        raise OwnershipError("requested path does not match recorded worktree")
    _verify_ownership(ownership)

    try:
        git_text(
            ownership.repo_real_path,
            "worktree",
            "remove",
            "--force",
            "--",
            str(ownership.worktree_path),
        )
    except GitOperationError as exc:
        raise OwnershipError("git refused to remove the owned worktree") from exc
    if ownership.worktree_path.exists():
        raise OwnershipError("git reported success but the worktree still exists")

    record_path = ownership_record_path(task_id, harness_dir=harness_dir)
    try:
        record_path.unlink()
    except OSError as exc:
        raise OwnershipError("worktree removed but ownership cleanup failed") from exc
    return ownership


def discard_owned_worktree(
    task_id: str, *, harness_dir: str | Path
) -> WorktreeOwnership:
    """Trusted CLI entry point: derive the cleanup path from ownership metadata."""
    ownership = load_ownership(task_id, harness_dir=harness_dir)
    return discard_worktree(
        task_id, ownership.worktree_path, harness_dir=harness_dir
    )
