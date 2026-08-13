from __future__ import annotations

from pathlib import Path

from guardedcoder.errors import FenceError, FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation
from guardedcoder.tools.paths import resolve_under_worktree

MAX_BYTES = 65_536


def _decode_text_prefix(data: bytes, truncated: bool) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        if (
            truncated
            and exc.reason == "unexpected end of data"
            and exc.start >= len(data) - 3
        ):
            return data[: exc.start].decode("utf-8", errors="strict")
        raise FileToolError("file is binary or not valid UTF-8") from exc


def read_file(worktree: Path, path: str) -> Observation:
    fence = check_path(worktree, path)
    if fence != FenceCode.ok:
        raise FenceError(fence)

    file_path = resolve_under_worktree(worktree, path)
    if not file_path.is_file():
        raise FileToolError("path is not a file")

    try:
        with file_path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise FileToolError("file cannot be read") from exc

    if b"\x00" in data:
        raise FileToolError("file is binary or not valid UTF-8")

    truncated = len(data) > MAX_BYTES
    body = _decode_text_prefix(data[:MAX_BYTES], truncated)
    return Observation(body=body, truncated=truncated)
