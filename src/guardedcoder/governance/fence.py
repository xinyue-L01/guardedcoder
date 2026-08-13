from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from guardedcoder.tools.paths import is_inside_worktree, resolve_under_worktree


class FenceCode(StrEnum):
    ok = "ok"
    WORKSPACE_ESCAPE = "WORKSPACE_ESCAPE"
    SENSITIVE_PATH = "SENSITIVE_PATH"


def _is_env_name(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def _is_sensitive(path: Path) -> bool:
    return any(_is_env_name(part) for part in path.parts)


def check_path(worktree: Path, user_path: str) -> FenceCode:
    resolved = resolve_under_worktree(worktree, user_path)
    if not is_inside_worktree(worktree, resolved):
        return FenceCode.WORKSPACE_ESCAPE
    if _is_sensitive(resolved) or _is_env_name(Path(user_path).name):
        return FenceCode.SENSITIVE_PATH
    return FenceCode.ok
