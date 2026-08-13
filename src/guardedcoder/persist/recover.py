from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from guardedcoder.errors import StaleRevisionError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.persist.txn import write_txn


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
) -> None:
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
            "SELECT worktree_identity, state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise LookupError(f"task {task_id} not found")
        owned = Path(task["worktree_identity"]).resolve()
        kind = win["action_kind"]
        if workspace != owned or not workspace.is_dir():
            new_status = "error"
            new_run_state = "error"
        elif kind == "run_command":
            new_status = "error"
            new_run_state = "error"
        elif kind != "apply_patch":
            raise NotImplementedError(
                f"recovery for action_kind {kind!r} is not implemented"
            )
        else:
            preimage = json.loads(win["preimage_json"]) if win["preimage_json"] else None
            postimage = json.loads(win["postimage_json"]) if win["postimage_json"] else None
            match_post = _matches_image(workspace, postimage)
            match_pre = _matches_image(workspace, preimage)
            if match_post is None or match_pre is None:
                new_status = "error"
                new_run_state = "error"
            elif match_post:
                new_status = "succeeded"
                new_run_state = "running"
            elif match_pre:
                cur = conn.execute(
                    "UPDATE tasks SET state_revision = state_revision + 1 "
                    "WHERE task_id = ? AND state_revision = ?",
                    (task_id, expected_revision),
                )
                if cur.rowcount == 0:
                    raise StaleRevisionError(
                        f"stale revision for task {task_id}: expected {expected_revision}"
                    )
                return
            else:
                new_status = "error"
                new_run_state = "error"

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
