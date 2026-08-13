"""Trusted workspace lifecycle operations."""

from guardedcoder.workspace.discard import discard_owned_worktree, discard_worktree
from guardedcoder.workspace.gitops import DirtyWorktreeError, assert_clean
from guardedcoder.workspace.worktree import (
    OwnershipError,
    WorktreeOwnership,
    create_task_worktree,
    load_ownership,
)

__all__ = [
    "DirtyWorktreeError",
    "OwnershipError",
    "WorktreeOwnership",
    "assert_clean",
    "create_task_worktree",
    "discard_owned_worktree",
    "discard_worktree",
    "load_ownership",
]
