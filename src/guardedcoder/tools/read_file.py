from __future__ import annotations

from pathlib import Path

from guardedcoder.errors import FenceError, FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation
from guardedcoder.tools.paths import resolve_under_worktree

MAX_BYTES = 65_536


def _readline_capped(stream, cap: int) -> tuple[bytes, bool]:
    line = stream.readline(cap + 1)
    if len(line) > cap and not line.endswith(b"\n"):
        while True:
            piece = stream.readline(cap)
            if not piece or piece.endswith(b"\n"):
                break
        return line[:cap], True
    return line, False


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
        raise FileToolError("file is binary or not valid UTF-8") from None


def read_file(
    worktree: Path,
    path: str,
    *,
    start_line: int = 1,
    end_line: int | None = None,
) -> Observation:
    fence = check_path(worktree, path)
    if fence != FenceCode.ok:
        raise FenceError(fence)

    if start_line < 1 or (end_line is not None and end_line < start_line):
        raise FileToolError("invalid line range")

    file_path = resolve_under_worktree(worktree, path)
    if not file_path.is_file():
        raise FileToolError("path is not a file")

    try:
        with file_path.open("rb") as stream:
            for _ in range(start_line - 1):
                skipped, _skipped_trunc = _readline_capped(stream, MAX_BYTES)
                if not skipped:
                    break
                if b"\x00" in skipped:
                    raise FileToolError("file is binary or not valid UTF-8")
            collected = bytearray()
            truncated = False
            current = start_line
            while end_line is None or current <= end_line:
                line, line_trunc = _readline_capped(stream, MAX_BYTES)
                if not line:
                    break
                if b"\x00" in line:
                    raise FileToolError("file is binary or not valid UTF-8")
                if line_trunc or len(collected) + len(line) > MAX_BYTES:
                    collected.extend(line[: MAX_BYTES - len(collected)])
                    truncated = True
                    break
                collected.extend(line)
                current += 1
    except OSError:
        raise FileToolError("file cannot be read") from None

    text = _decode_text_prefix(bytes(collected), truncated)
    return Observation(body=text, truncated=truncated)
