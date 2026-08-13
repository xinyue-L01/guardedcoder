from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from guardedcoder.tools.paths import is_inside_worktree, resolve_under_worktree


class FenceCode(StrEnum):
    ok = "ok"
    WORKSPACE_ESCAPE = "WORKSPACE_ESCAPE"
    SENSITIVE_PATH = "SENSITIVE_PATH"


def _is_env_name(name: str) -> bool:
    lowered = name.lower()
    return lowered == ".env" or lowered.startswith(".env.")


def _is_sensitive(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return any(_is_env_name(part) for part in relative.parts)


def check_path(worktree: Path, user_path: str) -> FenceCode:
    resolved = resolve_under_worktree(worktree, user_path)
    root = worktree.resolve()
    if not is_inside_worktree(worktree, resolved):
        return FenceCode.WORKSPACE_ESCAPE
    if _is_sensitive(resolved, root) or _is_env_name(Path(user_path).name):
        return FenceCode.SENSITIVE_PATH
    return FenceCode.ok
