from __future__ import annotations

from heapq import nsmallest
from pathlib import Path

from guardedcoder.errors import FenceError, FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation
from guardedcoder.tools.paths import resolve_under_worktree

MAX_ENTRIES = 256


def list_dir(worktree: Path, path: str) -> Observation:
    fence = check_path(worktree, path)
    if fence != FenceCode.ok:
        raise FenceError(fence)

    directory = resolve_under_worktree(worktree, path)
    if not directory.is_dir():
        raise FileToolError("path is not a directory")

    try:
        entries = nsmallest(
            MAX_ENTRIES + 1,
            directory.iterdir(),
            key=lambda entry: entry.name,
        )
    except OSError as exc:
        raise FileToolError("directory cannot be listed") from exc

    truncated = len(entries) > MAX_ENTRIES
    body = "\n".join(entry.name for entry in entries[:MAX_ENTRIES])
    return Observation(body=body, truncated=truncated)
