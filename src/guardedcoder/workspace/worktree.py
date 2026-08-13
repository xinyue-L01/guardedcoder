from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from guardedcoder.workspace.gitops import assert_clean, git_text

_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_WINDOWS_DEVICE = re.compile(
    r"(?i)^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\.[^.].*)?\Z"
)
_COMMIT_ID = re.compile(r"[0-9a-fA-F]{4,64}\Z")
_OWNERSHIP_FIELDS = frozenset(
    {"task_id", "repo_real_path", "base_commit", "worktree_path"}
)


class OwnershipError(RuntimeError):
    """Raised when a workspace path does not match trusted ownership metadata."""


@dataclass(frozen=True)
class WorktreeOwnership:
    task_id: str
    repo_real_path: Path
    base_commit: str
    worktree_path: Path


def validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise ValueError("task_id must contain only letters, digits, '.', '_' or '-'")
    if task_id in {".", ".."}:
        raise ValueError("task_id cannot be a path segment")
    if task_id.endswith((".", " ", "\t")):
        raise ValueError("task_id cannot end with a dot or whitespace")
    if _WINDOWS_DEVICE.fullmatch(task_id) is not None:
        raise ValueError("task_id cannot be a Windows device name")


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _harness_root(harness_dir: str | Path) -> Path:
    return Path(harness_dir).expanduser().resolve()


def ownership_record_path(
    task_id: str, *, harness_dir: str | Path
) -> Path:
    validate_task_id(task_id)
    return _harness_root(harness_dir) / "ownership" / f"{task_id}.json"


def _expected_worktree_path(task_id: str, harness_dir: str | Path) -> Path:
    validate_task_id(task_id)
    return _absolute(_harness_root(harness_dir) / "worktrees" / task_id)


def _serialize(ownership: WorktreeOwnership) -> str:
    return json.dumps(
        {
            "task_id": ownership.task_id,
            "repo_real_path": str(ownership.repo_real_path),
            "base_commit": ownership.base_commit,
            "worktree_path": str(ownership.worktree_path),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_ownership(
    ownership: WorktreeOwnership, *, harness_dir: str | Path
) -> None:
    record_path = ownership_record_path(
        ownership.task_id, harness_dir=harness_dir
    )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with record_path.open("x", encoding="utf-8", newline="\n") as record:
            record.write(_serialize(ownership))
            record.write("\n")
    except FileExistsError as exc:
        raise OwnershipError(
            f"ownership already exists for task {ownership.task_id}"
        ) from exc


def load_ownership(
    task_id: str, *, harness_dir: str | Path
) -> WorktreeOwnership:
    record_path = ownership_record_path(task_id, harness_dir=harness_dir)
    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnershipError(f"invalid ownership record for task {task_id}") from exc
    if not isinstance(raw, dict) or set(raw) != _OWNERSHIP_FIELDS:
        raise OwnershipError(f"invalid ownership record for task {task_id}")
    if raw.get("task_id") != task_id:
        raise OwnershipError(f"ownership task mismatch for task {task_id}")
    if not all(
        isinstance(raw.get(field), str)
        for field in ("repo_real_path", "base_commit", "worktree_path")
    ):
        raise OwnershipError(f"invalid ownership record for task {task_id}")
    base_commit = raw["base_commit"]
    if _COMMIT_ID.fullmatch(base_commit) is None:
        raise OwnershipError(f"invalid ownership base commit for task {task_id}")

    recorded_worktree = _absolute(raw["worktree_path"])
    expected_worktree = _expected_worktree_path(task_id, harness_dir)
    if recorded_worktree != expected_worktree:
        raise OwnershipError(f"ownership path mismatch for task {task_id}")
    repo_path = _absolute(raw["repo_real_path"])
    if recorded_worktree == repo_path:
        raise OwnershipError(f"worktree aliases origin for task {task_id}")
    return WorktreeOwnership(
        task_id=task_id,
        repo_real_path=repo_path,
        base_commit=base_commit.lower(),
        worktree_path=recorded_worktree,
    )


def create_task_worktree(
    *,
    task_id: str,
    repo_path: str | Path,
    base_commit: str,
    harness_dir: str | Path,
) -> WorktreeOwnership:
    """Create a detached task worktree and persist its trusted ownership."""
    validate_task_id(task_id)
    if not isinstance(base_commit, str) or _COMMIT_ID.fullmatch(base_commit) is None:
        raise ValueError("base_commit must be a fixed hexadecimal commit id")

    repo_root = assert_clean(repo_path)
    harness_root = _harness_root(harness_dir)
    if harness_root == repo_root or harness_root.is_relative_to(repo_root):
        raise OwnershipError("harness directory must be outside the origin repository")

    canonical_base = git_text(
        repo_root, "rev-parse", "--verify", f"{base_commit}^{{commit}}"
    ).lower()
    if _COMMIT_ID.fullmatch(canonical_base) is None:
        raise OwnershipError("git returned an invalid base commit")

    worktree_path = _expected_worktree_path(task_id, harness_root)
    record_path = ownership_record_path(task_id, harness_dir=harness_root)
    if worktree_path.exists() or record_path.exists():
        raise OwnershipError(f"workspace already exists for task {task_id}")

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    git_text(
        repo_root,
        "worktree",
        "add",
        "--detach",
        str(worktree_path),
        canonical_base,
    )
    ownership = WorktreeOwnership(
        task_id=task_id,
        repo_real_path=repo_root,
        base_commit=canonical_base,
        worktree_path=worktree_path,
    )
    try:
        _write_ownership(ownership, harness_dir=harness_root)
    except Exception:
        try:
            git_text(
                repo_root,
                "worktree",
                "remove",
                "--force",
                "--",
                str(worktree_path),
            )
        except Exception as cleanup_exc:
            raise OwnershipError(
                "ownership recording failed and created worktree could not be removed"
            ) from cleanup_exc
        raise
    return ownership
