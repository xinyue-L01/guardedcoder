from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from guardedcoder.errors import StaleRevisionError
from guardedcoder.persist.store import update_task


def _read_workspace_file(workspace: Path, rel: str) -> str | None:
    path = workspace / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _matches_image(workspace: Path, image: dict[str, str] | None) -> bool:
    if not image:
        return False
    for rel, expected in image.items():
        actual = _read_workspace_file(workspace, rel)
        if actual != expected:
            return False
    return True


def recover(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    workspace: Path,
    expected_revision: int,
) -> None:
    conn.row_factory = sqlite3.Row
    win = conn.execute(
        "SELECT * FROM execution_windows WHERE task_id = ? "
        "AND status = ? ORDER BY rowid DESC",
        (task_id, "executing_action"),
    ).fetchone()
    if win is None:
        raise LookupError(f"no open execution window for task {task_id}")
    if win["action_kind"] != "apply_patch":
        raise NotImplementedError(
            f"recovery for action_kind {win['action_kind']!r} is not implemented"
        )
    preimage = json.loads(win["preimage_json"]) if win["preimage_json"] else None
    postimage = json.loads(win["postimage_json"]) if win["postimage_json"] else None
    match_post = _matches_image(workspace, postimage)
    match_pre = _matches_image(workspace, preimage)
    if match_post:
        new_status = "succeeded"
        new_run_state = "running"
    elif match_pre:
        return
    else:
        new_status = "error"
        new_run_state = "error"

    conn.execute("SAVEPOINT sp_recover")
    try:
        update_task(
            conn,
            task_id,
            expected_revision=expected_revision,
            run_state=new_run_state,
        )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            (new_status, win["window_id"]),
        )
        conn.execute("RELEASE SAVEPOINT sp_recover")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_recover")
        conn.execute("RELEASE SAVEPOINT sp_recover")
        raise
