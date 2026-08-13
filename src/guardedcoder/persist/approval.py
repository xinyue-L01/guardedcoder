from __future__ import annotations

import sqlite3
import uuid

from guardedcoder.errors import ApprovalError, PendingConsumedError


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
    task = conn.execute(
        "SELECT state_revision, envelope_hash FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ApprovalError(f"task {task_id} not found")
    current_revision, envelope_hash = task[0], task[1]
    del envelope_hash

    pending = conn.execute(
        "SELECT pending_action_id, fingerprint, state_revision, consumed "
        "FROM pending_actions WHERE task_id = ? ORDER BY consumed ASC",
        (task_id,),
    ).fetchone()
    if pending is None:
        raise ApprovalError(f"no pending action for task {task_id}")

    pending_id, stored_fp, bound_revision, consumed = pending
    if consumed:
        raise PendingConsumedError(
            f"pending action {pending_id} already consumed"
        )
    if stored_fp != fingerprint:
        raise ApprovalError(
            f"fingerprint mismatch for task {task_id}"
        )
    if bound_revision != current_revision:
        raise ApprovalError(
            f"stale pending revision for task {task_id}: "
            f"bound {bound_revision} current {current_revision}"
        )

    cur = conn.execute(
        "UPDATE pending_actions SET consumed = 1 "
        "WHERE pending_action_id = ? AND consumed = 0 "
        "AND fingerprint = ? AND state_revision = ?",
        (pending_id, fingerprint, current_revision),
    )
    if cur.rowcount != 1:
        raise PendingConsumedError(
            f"pending action {pending_id} already consumed"
        )
    return pending_id
