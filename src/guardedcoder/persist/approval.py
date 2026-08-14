from __future__ import annotations

import sqlite3
import uuid

from guardedcoder.errors import ApprovalError, PendingConsumedError, StaleRevisionError
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
        task = conn.execute(
            "SELECT run_state, state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise ApprovalError(f"task {task_id} not found")
        if task[0] != "awaiting_approval":
            raise ApprovalError(
                f"insert_pending requires awaiting_approval, got {task[0]!r}"
            )
        if task[1] != state_revision:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {state_revision}"
            )
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


def request_approval(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    fingerprint: str,
    normalized_action_json: str,
    expected_revision: int,
    pending_action_id: str | None = None,
) -> str:
    pending_id = pending_action_id or str(uuid.uuid4())
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ? AND run_state = ?",
            ("awaiting_approval", task_id, expected_revision, "running"),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        conn.execute(
            "INSERT INTO pending_actions ("
            "pending_action_id, task_id, fingerprint, normalized_action_json, "
            "state_revision, consumed) VALUES (?, ?, ?, ?, ?, 0)",
            (
                pending_id,
                task_id,
                fingerprint,
                normalized_action_json,
                expected_revision + 1,
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


def reject(conn: sqlite3.Connection, task_id: str, fingerprint: str) -> str:
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
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND run_state = ? AND state_revision = ?",
            ("running", task_id, "awaiting_approval", bound_revision),
        )
        if cur.rowcount != 1:
            raise ApprovalError(
                f"reject could not return task {task_id} to running"
            )
        return pending_id
