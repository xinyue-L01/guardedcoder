from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from guardedcoder.errors import FenceError, PatchError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.observation import Observation

MAX_FILES = 16
MAX_PATCH_BYTES = 65_536
MAX_CHANGED_LINES = 2_000

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class PatchApplyResult:
    observation: Observation
    preimage: dict[str, dict[str, object]]
    postimage: dict[str, dict[str, object]]


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[_Hunk, ...]


def _norm_header_path(raw: str) -> str | None:
    text = raw.split("\t", 1)[0].strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text in {"/dev/null", "a/dev/null", "b/dev/null"}:
        return None
    if text.startswith("a/") or text.startswith("b/"):
        text = text[2:]
    text = text.replace("\\", "/")
    if not text:
        raise PatchError("malformed diff")
    return text


def _parse_diff(diff: str) -> list[_FilePatch]:
    if "GIT binary patch" in diff or "\0" in diff:
        raise PatchError("binary patch")
    lines = diff.splitlines()
    files: list[_FilePatch] = []
    rename_from: str | None = None
    rename_to: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("rename from "):
            rename_from = line[12:].replace("\\", "/")
            index += 1
            continue
        if line.startswith("rename to "):
            rename_to = line[10:].replace("\\", "/")
            index += 1
            continue
        if line.startswith(("diff --git ", "index ", "similarity ", "new file ", "deleted file ")):
            index += 1
            continue
        if line.startswith("--- "):
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise PatchError("malformed diff")
            old_path = _norm_header_path(line[4:])
            new_path = _norm_header_path(lines[index + 1][4:])
            if old_path is None and rename_from is not None:
                old_path = rename_from
            if new_path is None and rename_to is not None:
                new_path = rename_to
            if old_path is None and new_path is None:
                raise PatchError("malformed diff")
            index += 2
            hunks: list[_Hunk] = []
            while index < len(lines) and lines[index].startswith("@@ "):
                match = _HUNK.match(lines[index])
                if match is None:
                    raise PatchError("malformed hunk")
                index += 1
                body: list[str] = []
                while index < len(lines) and lines[index][:1] in {" ", "+", "-", "\\"}:
                    body.append(lines[index])
                    index += 1
                hunks.append(
                    _Hunk(
                        old_start=int(match.group(1)),
                        old_count=int(match.group(2) or "1"),
                        new_start=int(match.group(3)),
                        new_count=int(match.group(4) or "1"),
                        lines=tuple(body),
                    )
                )
            files.append(_FilePatch(old_path, new_path, tuple(hunks)))
            rename_from = None
            rename_to = None
            continue
        if line.startswith("@@"):
            raise PatchError("malformed diff")
        index += 1
    if not files and rename_from and rename_to:
        files.append(_FilePatch(rename_from, rename_to, ()))
    if not files:
        raise PatchError("malformed diff")
    return files


def _strip_nl(value: str) -> str:
    return value[:-1] if value.endswith("\n") else value


def _file_lines(text: str) -> list[str]:
    if text == "":
        return []
    lines = text.splitlines(keepends=True)
    if not text.endswith("\n") and lines:
        return lines
    return lines


def _apply_hunks(original: str, hunks: tuple[_Hunk, ...]) -> str:
    lines = _file_lines(original)
    cursor = 0
    output: list[str] = []
    for hunk in hunks:
        target = 0 if hunk.old_start == 0 else hunk.old_start - 1
        if target < cursor or target > len(lines):
            raise PatchError("hunk does not apply")
        output.extend(lines[cursor:target])
        cursor = target
        for raw in hunk.lines:
            if raw.startswith("\\"):
                if output:
                    output[-1] = _strip_nl(output[-1])
                continue
            tag = raw[:1]
            body = raw[1:]
            if tag == " ":
                if cursor >= len(lines) or _strip_nl(lines[cursor]) != body:
                    raise PatchError("hunk does not apply")
                output.append(lines[cursor])
                cursor += 1
            elif tag == "-":
                if cursor >= len(lines) or _strip_nl(lines[cursor]) != body:
                    raise PatchError("hunk does not apply")
                cursor += 1
            elif tag == "+":
                output.append(body + "\n")
            else:
                raise PatchError("malformed hunk")
    output.extend(lines[cursor:])
    return "".join(output)


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        raise PatchError("file cannot be read") from None
    if b"\x00" in data:
        raise PatchError("binary file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchError("binary file") from None


def _mark_bytes(data: bytes | None) -> dict[str, object]:
    if data is None:
        return {"exists": False, "sha256": None}
    return {"exists": True, "sha256": hashlib.sha256(data).hexdigest()}


def _fence(worktree: Path, rel: str) -> None:
    code = check_path(worktree, rel)
    if code != FenceCode.ok:
        raise FenceError(code)
    candidate = worktree / rel
    if candidate.is_symlink():
        raise PatchError("symlink")


def _involved_paths(file_patch: _FilePatch) -> list[str]:
    paths: list[str] = []
    if file_patch.old_path is not None:
        paths.append(file_patch.old_path)
    if file_patch.new_path is not None and file_patch.new_path not in paths:
        paths.append(file_patch.new_path)
    return paths


def apply_patch(
    worktree: Path,
    diff: str,
    *,
    allow_delete: bool = False,
) -> PatchApplyResult:
    encoded = diff.encode("utf-8")
    if len(encoded) > MAX_PATCH_BYTES:
        raise PatchError("patch too large")
    files = _parse_diff(diff)
    if len(files) > MAX_FILES:
        raise PatchError("too many files")

    changed_lines = 0
    for file_patch in files:
        for hunk in file_patch.hunks:
            changed_lines += sum(1 for line in hunk.lines if line[:1] in {"+", "-"})
    if changed_lines > MAX_CHANGED_LINES:
        raise PatchError("too many changed lines")

    root = worktree.resolve()
    all_paths: list[str] = []
    for file_patch in files:
        for rel in _involved_paths(file_patch):
            _fence(root, rel)
            if rel not in all_paths:
                all_paths.append(rel)

    planned: dict[str, bytes | None] = {}
    for file_patch in files:
        old_rel = file_patch.old_path
        new_rel = file_patch.new_path
        deleting = new_rel is None
        creating = old_rel is None
        renaming = (
            old_rel is not None and new_rel is not None and old_rel != new_rel
        )
        if (deleting or renaming) and not allow_delete:
            raise PatchError("delete not allowed")

        if creating:
            original = ""
        else:
            assert old_rel is not None
            source = root / old_rel
            if source.is_symlink():
                raise PatchError("symlink")
            if not source.is_file():
                raise PatchError("hunk does not apply")
            original = _read_text(source)

        updated = _apply_hunks(original, file_patch.hunks) if file_patch.hunks else original
        new_bytes = updated.encode("utf-8")
        if b"\x00" in new_bytes:
            raise PatchError("binary patch")

        if deleting:
            assert old_rel is not None
            planned[old_rel] = None
        elif renaming:
            assert old_rel is not None and new_rel is not None
            planned[new_rel] = new_bytes
            planned[old_rel] = None
        else:
            assert new_rel is not None
            planned[new_rel] = new_bytes

    preimage = {
        rel: _mark_bytes(
            None if not (root / rel).is_file() else (root / rel).read_bytes()
        )
        for rel in all_paths
    }
    postimage = {
        rel: _mark_bytes(planned[rel]) if rel in planned else preimage[rel]
        for rel in all_paths
    }

    temps: list[tuple[Path, Path]] = []
    try:
        for rel, data in planned.items():
            if data is None:
                continue
            dest = root / rel
            if dest.is_symlink():
                raise PatchError("symlink")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".gc-patch-tmp")
            tmp.write_bytes(data)
            temps.append((tmp, dest))
        for tmp, dest in temps:
            tmp.replace(dest)
        for rel, data in planned.items():
            if data is None:
                target = root / rel
                if target.is_symlink() or target.is_file():
                    target.unlink()
    except OSError:
        for tmp, _dest in temps:
            tmp.unlink(missing_ok=True)
        raise PatchError("patch could not be written") from None

    summary = []
    for rel, data in planned.items():
        summary.append(("delete" if data is None else "write") + " " + rel)
    body = "\n".join(summary)
    return PatchApplyResult(
        observation=Observation(
            body=body,
            truncated=False,
            artifact_sha256=hashlib.sha256(encoded).hexdigest(),
        ),
        preimage=preimage,
        postimage=postimage,
    )
