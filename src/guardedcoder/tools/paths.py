from __future__ import annotations

from pathlib import Path


def resolve_under_worktree(worktree: Path, user_path: str) -> Path:
    root = worktree.resolve()
    candidate = Path(user_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def is_inside_worktree(worktree: Path, resolved: Path) -> bool:
    root = worktree.resolve()
    return resolved.is_relative_to(root)
