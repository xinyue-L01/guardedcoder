from __future__ import annotations

import sqlite3
import uuid

from guardedcoder.errors import ApprovalError, PendingConsumedError
from guardedcoder.persist.txn import write_txn


def insert_pending(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    fingerprint: str,
    normalized_action_json: str,
    state_revision: int,
    pending_action_id: str | None = None,
) -> str:
    pending_id = pending_action_id or str(uuid.uuid4())
    with write_txn(conn):
        conn.execute(
            "INSERT INTO pending_actions ("
            "pending_action_id, task_id, fingerprint, normalized_action_json, "
            "state_revision, consumed) VALUES (?, ?, ?, ?, ?, 0)",
            (
                pending_id,
                task_id,
                fingerprint,
                normalized_action_json,
                state_revision,
            ),
        )
    return pending_id


def approve(conn: sqlite3.Connection, task_id: str, fingerprint: str) -> str:
    with write_txn(conn):
        pending = conn.execute(
            "SELECT pending_action_id, fingerprint, state_revision, consumed "
            "FROM pending_actions WHERE task_id = ? AND consumed = 0",
            (task_id,),
        ).fetchone()
        if pending is None:
            any_pending = conn.execute(
                "SELECT pending_action_id, consumed FROM pending_actions "
                "WHERE task_id = ? ORDER BY consumed DESC",
                (task_id,),
            ).fetchone()
            if any_pending is not None and any_pending[1]:
                raise PendingConsumedError(
                    f"pending action {any_pending[0]} already consumed"
                )
            raise ApprovalError(f"no pending action for task {task_id}")
        pending_id, stored_fp, bound_revision, consumed = pending
        del consumed
        if stored_fp != fingerprint:
            raise ApprovalError(f"fingerprint mismatch for task {task_id}")
        cur = conn.execute(
            "UPDATE pending_actions SET consumed = 1 "
            "WHERE pending_action_id = ? AND consumed = 0 "
            "AND fingerprint = ? AND state_revision = ("
            "SELECT state_revision FROM tasks WHERE task_id = ?"
            ")",
            (pending_id, fingerprint, task_id),
        )
        if cur.rowcount != 1:
            raise ApprovalError(
                f"stale pending revision for task {task_id}: "
                f"bound {bound_revision}"
            )
        return pending_id
