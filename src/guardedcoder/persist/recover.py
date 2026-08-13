from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from enum import StrEnum
from pathlib import Path
from typing import Any

from guardedcoder.errors import StaleRevisionError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.persist.txn import write_txn

_TERMINAL = frozenset(
    {
        "succeeded",
        "failed",
        "blocked",
        "unverified",
        "exhausted",
        "error",
    }
)


class RecoverDecision(StrEnum):
    retryable_same_attempt = "retryable_same_attempt"
    recorded_success = "recorded_success"
    recorded_error = "recorded_error"


def _file_mark(workspace: Path, rel: str) -> dict[str, object] | None:
    if check_path(workspace, rel) != FenceCode.ok:
        return None
    path = workspace / rel
    if path.is_symlink():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return {"exists": False, "sha256": None}
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        return {"exists": True, "sha256": hasher.hexdigest()}
    finally:
        os.close(fd)


def _matches_image(workspace: Path, image: dict | None) -> bool | None:
    if not image:
        return False
    for rel, expected in image.items():
        actual = _file_mark(workspace, rel)
        if actual is None:
            return None
        if actual != expected:
            return False
    return True


def recover(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    workspace: Path,
    expected_revision: int,
    executor: Any = None,
) -> RecoverDecision:
    del executor
    workspace = workspace.resolve()
    conn.row_factory = sqlite3.Row
    with write_txn(conn):
        win = conn.execute(
            "SELECT * FROM execution_windows WHERE task_id = ? "
            "AND status = ? ORDER BY rowid DESC",
            (task_id, "executing_action"),
        ).fetchone()
        if win is None:
            raise LookupError(f"no open execution window for task {task_id}")
        task = conn.execute(
            "SELECT worktree_identity, state_revision, run_state FROM tasks "
            "WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise LookupError(f"task {task_id} not found")
        if task["state_revision"] != expected_revision:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )

        owned = Path(task["worktree_identity"]).resolve()
        opened_revision = win["opened_revision"]
        source_run_state = win["source_run_state"]
        kind = win["action_kind"]
        live_ok = (
            source_run_state == "verifying" and task["run_state"] == "verifying"
        ) or (
            source_run_state == "running" and task["run_state"] == "executing_action"
        )
        inconsistent = (
            opened_revision is None
            or source_run_state not in {"running", "verifying"}
            or opened_revision != expected_revision
            or opened_revision != task["state_revision"]
            or task["run_state"] in _TERMINAL
            or not live_ok
        )
        new_status = "error"
        new_run_state = "error"
        decision = RecoverDecision.recorded_error
        if workspace != owned or not workspace.is_dir() or inconsistent:
            pass
        elif kind != "apply_patch":
            pass
        else:
            try:
                preimage = (
                    json.loads(win["preimage_json"]) if win["preimage_json"] else None
                )
                postimage = (
                    json.loads(win["postimage_json"]) if win["postimage_json"] else None
                )
            except (TypeError, json.JSONDecodeError, ValueError):
                preimage, postimage = None, None
            if (
                not isinstance(preimage, dict)
                or not isinstance(postimage, dict)
                or not preimage
                or set(preimage) != set(postimage)
            ):
                pass
            else:
                match_post = _matches_image(workspace, postimage)
                match_pre = _matches_image(workspace, preimage)
                if match_post is None or match_pre is None:
                    pass
                elif match_post:
                    new_status = "succeeded"
                    new_run_state = (
                        "verifying" if source_run_state == "verifying" else "running"
                    )
                    decision = RecoverDecision.recorded_success
                elif match_pre:
                    return RecoverDecision.retryable_same_attempt
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ?",
            (new_run_state, task_id, expected_revision),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            (new_status, win["window_id"]),
        )
        return decision
