from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from guardedcoder.errors import UnauthorizedError
from guardedcoder.models.actions import (
    Action,
    ApplyPatchAction,
    ListDirAction,
    ReadFileAction,
    RunCommandAction,
    SearchTextAction,
)
from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.persist.txn import write_txn
from guardedcoder.tools.apply_patch import apply_patch
from guardedcoder.tools.list_dir import list_dir
from guardedcoder.tools.read_file import read_file
from guardedcoder.tools.run_command import run_command
from guardedcoder.tools.search_text import search_text


def _file_mark(workspace: Path, rel: str) -> dict[str, object]:
    path = workspace / rel
    if not path.is_file() or path.is_symlink():
        return {"exists": False, "sha256": None}
    return {
        "exists": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _matches(workspace: Path, image: dict[str, object] | None) -> bool:
    if not isinstance(image, dict) or not image:
        return False
    for rel, expected in image.items():
        if _file_mark(workspace, rel) != expected:
            return False
    return True


def _authorize(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    permit_id: str,
    window_id: str,
    claim_id: str | None,
    action: Action,
) -> sqlite3.Row | tuple:
    permit = conn.execute(
        "SELECT consumed, task_id FROM permits WHERE permit_id = ?",
        (permit_id,),
    ).fetchone()
    if permit is None or permit[1] != task_id or not permit[0]:
        raise UnauthorizedError("permit is missing or not consumed")
    window = conn.execute(
        "SELECT task_id, permit_id, action_kind, status, execution_started, "
        "preimage_json, postimage_json FROM execution_windows WHERE window_id = ?",
        (window_id,),
    ).fetchone()
    if (
        window is None
        or window[0] != task_id
        or window[1] != permit_id
        or window[3] != "executing_action"
    ):
        raise UnauthorizedError("execution window is missing or inactive")
    kind = window[2]
    started = bool(window[4])
    if isinstance(action, ApplyPatchAction) and kind != "apply_patch":
        raise UnauthorizedError("window action mismatch")
    if isinstance(action, RunCommandAction) and kind != "run_command":
        raise UnauthorizedError("window action mismatch")
    if isinstance(action, ApplyPatchAction) and started:
        if claim_id is None:
            raise UnauthorizedError("recovered apply_patch requires a claim")
        claim = conn.execute(
            "SELECT consumed, task_id, window_id, state_revision FROM "
            "recovered_attempt_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        task = conn.execute(
            "SELECT state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if (
            claim is None
            or claim[0]
            or claim[1] != task_id
            or claim[2] != window_id
            or task is None
            or claim[3] != task[0]
        ):
            raise UnauthorizedError("claim is missing, stale, or replayed")
        cur = conn.execute(
            "UPDATE recovered_attempt_claims SET consumed = 1 "
            "WHERE claim_id = ? AND consumed = 0",
            (claim_id,),
        )
        if cur.rowcount != 1:
            raise UnauthorizedError("claim is missing, stale, or replayed")
    if isinstance(action, ApplyPatchAction) and not started:
        conn.execute(
            "UPDATE execution_windows SET execution_started = 1 WHERE window_id = ?",
            (window_id,),
        )
    return window


def execute(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    permit_id: str,
    window_id: str,
    action: Action,
    worktree: Path,
    claim_id: str | None = None,
    task_dir: Path | None = None,
    envelope: Envelope | None = None,
) -> Observation | CommandResult:
    with write_txn(conn):
        window = _authorize(
            conn,
            task_id=task_id,
            permit_id=permit_id,
            window_id=window_id,
            claim_id=claim_id,
            action=action,
        )

    if isinstance(action, ApplyPatchAction):
        preimage = json.loads(window[5]) if window[5] else None
        postimage = json.loads(window[6]) if window[6] else None
        if _matches(worktree, postimage):
            return Observation(body="already applied", truncated=False)
        if not _matches(worktree, preimage):
            raise UnauthorizedError("pre/post image mismatch")
        return apply_patch(worktree, action.diff).observation

    if isinstance(action, ListDirAction):
        return list_dir(worktree, action.path)
    if isinstance(action, ReadFileAction):
        return read_file(worktree, action.path)
    if isinstance(action, SearchTextAction):
        read_paths = envelope.read_paths if envelope is not None else None
        return search_text(worktree, action.query, read_paths=read_paths)
    if isinstance(action, RunCommandAction):
        if envelope is None:
            raise UnauthorizedError("run_command requires a confirmed profile")
        profile = next(
            (item for item in envelope.profiles if item.profile_id == action.profile_id),
            None,
        )
        if profile is None:
            raise UnauthorizedError("unknown command profile")
        if task_dir is None:
            raise UnauthorizedError("run_command requires task_dir")
        return run_command(worktree, profile, task_dir=task_dir)
    raise UnauthorizedError("unsupported action")
