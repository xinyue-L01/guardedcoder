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
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return False
    return not str(relative).startswith("..")
