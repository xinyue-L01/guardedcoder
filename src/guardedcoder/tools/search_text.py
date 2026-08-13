from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from guardedcoder.errors import FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation

MAX_FILES = 64
MAX_MATCHES = 50
MAX_OUTPUT_BYTES = 65_536


def _allowed_files(root: Path) -> Iterator[tuple[Path, str]]:
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        allowed_directories: list[str] = []
        for name in sorted(directory_names):
            relative = (current / name).relative_to(root).as_posix()
            if check_path(root, relative) == FenceCode.ok:
                allowed_directories.append(name)
        directory_names[:] = allowed_directories

        for name in sorted(file_names):
            candidate = current / name
            relative = candidate.relative_to(root).as_posix()
            if check_path(root, relative) != FenceCode.ok:
                continue
            if candidate.is_file():
                yield candidate, relative


def _matching_records(
    file_path: Path,
    relative: str,
    query: str,
    limit: int,
) -> tuple[list[str], bool] | None:
    records: list[str] = []
    overflow = False
    try:
        with file_path.open("r", encoding="utf-8", errors="strict") as stream:
            for line_number, line in enumerate(stream, start=1):
                if "\x00" in line:
                    return None
                if query not in line:
                    continue
                record = f"{relative}:{line_number}:{line.rstrip('\r\n')}"
                if len(records) < limit:
                    records.append(record)
                else:
                    overflow = True
    except (OSError, UnicodeDecodeError):
        return None
    return records, overflow


def _utf8_prefix(value: str, byte_limit: int) -> str:
    return value.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def search_text(worktree: Path, query: str) -> Observation:
    root = worktree.resolve()
    if not root.is_dir():
        raise FileToolError("worktree is not a directory")

    body = ""
    match_count = 0
    files_seen = 0

    for file_path, relative in _allowed_files(root):
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
        records, overflow = result

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

        if overflow:
            return Observation(body=body, truncated=True)

    return Observation(body=body, truncated=False)
