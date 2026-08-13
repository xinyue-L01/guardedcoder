from __future__ import annotations

import sqlite3
import uuid

from guardedcoder.errors import ClaimConflictError, StaleRevisionError, UnauthorizedError
from guardedcoder.persist.txn import write_txn


def claim_recovered_attempt(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    window_id: str,
    expected_revision: int,
    attempt_id: str,
) -> str:
    claim_id = str(uuid.uuid4())
    with write_txn(conn):
        task = conn.execute(
            "SELECT state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None or task[0] != expected_revision:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        window = conn.execute(
            "SELECT task_id, status FROM execution_windows WHERE window_id = ?",
            (window_id,),
        ).fetchone()
        if (
            window is None
            or window[0] != task_id
            or window[1] != "executing_action"
        ):
            raise UnauthorizedError("no recoverable apply_patch window")
        try:
            conn.execute(
                "INSERT INTO recovered_attempt_claims ("
                "claim_id, task_id, window_id, state_revision, attempt_id, consumed"
                ") VALUES (?, ?, ?, ?, ?, 0)",
                (claim_id, task_id, window_id, expected_revision, attempt_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ClaimConflictError(
                f"recovered attempt already claimed for window {window_id}"
            ) from exc
    return claim_id
