from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from guardedcoder.errors import FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation
from guardedcoder.tools.paths import is_inside_worktree, resolve_under_worktree

MAX_FILES = 64
MAX_MATCHES = 50
MAX_OUTPUT_BYTES = 65_536
_SKIP_DIR_NAMES = frozenset({".git", ".venv", ".pytest_cache", "__pycache__"})


def _under_read_paths(root: Path, read_paths: tuple[str, ...], relative: str) -> bool:
    resolved = resolve_under_worktree(root, relative)
    for allowed_path in read_paths:
        allowed = resolve_under_worktree(root, allowed_path)
        if not is_inside_worktree(root, allowed):
            continue
        if resolved == allowed or resolved.is_relative_to(allowed):
            return True
    return False


def _dir_may_reach_read_paths(
    root: Path, read_paths: tuple[str, ...], relative: str
) -> bool:
    resolved = resolve_under_worktree(root, relative)
    for allowed_path in read_paths:
        allowed = resolve_under_worktree(root, allowed_path)
        if not is_inside_worktree(root, allowed):
            continue
        if (
            resolved == allowed
            or resolved.is_relative_to(allowed)
            or allowed.is_relative_to(resolved)
        ):
            return True
    return False


def _allowed_files(
    root: Path, read_paths: tuple[str, ...] | None
) -> Iterator[tuple[Path, str]]:
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        allowed_directories: list[str] = []
        for name in sorted(directory_names):
            if name in _SKIP_DIR_NAMES or name.startswith("."):
                continue
            relative = (current / name).relative_to(root).as_posix()
            if check_path(root, relative) != FenceCode.ok:
                continue
            if read_paths is not None and not _dir_may_reach_read_paths(
                root, read_paths, relative
            ):
                continue
            allowed_directories.append(name)
        directory_names[:] = allowed_directories

        for name in sorted(file_names):
            candidate = current / name
            relative = candidate.relative_to(root).as_posix()
            if check_path(root, relative) != FenceCode.ok:
                continue
            if read_paths is not None and not _under_read_paths(root, read_paths, relative):
                continue
            if candidate.is_file():
                yield candidate, relative


def _matching_records(
    file_path: Path,
    relative: str,
    query: str,
    limit: int,
) -> tuple[list[str], bool, bool] | None:
    records: list[str] = []
    file_truncated = False
    match_overflow = False
    try:
        with file_path.open("rb") as stream:
            data = stream.read(MAX_OUTPUT_BYTES + 1)
    except OSError:
        return None
    if b"\x00" in data:
        return None
    if len(data) > MAX_OUTPUT_BYTES:
        file_truncated = True
        data = data[:MAX_OUTPUT_BYTES]
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        if not file_truncated:
            return None
        text = data.decode("utf-8", errors="ignore")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if query not in line:
            continue
        record = f"{relative}:{line_number}:{line}"
        if len(records) < limit:
            records.append(record)
        else:
            match_overflow = True
    return records, file_truncated, match_overflow


def _utf8_prefix(value: str, byte_limit: int) -> str:
    return value.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def search_text(
    worktree: Path,
    query: str,
    *,
    read_paths: tuple[str, ...] | None = None,
) -> Observation:
    root = worktree.resolve()
    if not root.is_dir():
        raise FileToolError("worktree is not a directory")
    if query == "":
        raise FileToolError("empty query")

    body = ""
    match_count = 0
    files_seen = 0
    truncated = False

    for file_path, relative in _allowed_files(root, read_paths):
        if files_seen >= MAX_FILES:
            return Observation(body=body, truncated=True)
        files_seen += 1

        result = _matching_records(
            file_path,
            relative,
            query,
            MAX_MATCHES - match_count + 1,
        )
        if result is None:
            continue
        records, file_truncated, match_overflow = result
        truncated = truncated or file_truncated

        for record in records:
            if match_count >= MAX_MATCHES:
                return Observation(body=body, truncated=True)
            addition = ("\n" if body else "") + record
            available = MAX_OUTPUT_BYTES - len(body.encode("utf-8"))
            encoded_size = len(addition.encode("utf-8"))
            if encoded_size > available:
                body += _utf8_prefix(addition, available)
                return Observation(body=body, truncated=True)
            body += addition
            match_count += 1

        if match_overflow:
            return Observation(body=body, truncated=True)

    return Observation(body=body, truncated=truncated)
