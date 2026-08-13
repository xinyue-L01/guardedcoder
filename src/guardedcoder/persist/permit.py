from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from guardedcoder.errors import PermitConsumedError, PermitInvalidError, StaleRevisionError


def create_permit(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    action_id: str,
    fingerprint: str,
    envelope_hash: str,
    expected_revision: int,
    executor: Any = None,
) -> str:
    del executor
    permit_id = str(uuid.uuid4())
    conn.execute("SAVEPOINT sp_create_permit")
    try:
        cur = conn.execute(
            "UPDATE tasks SET remaining_steps = remaining_steps - 1, "
            "state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ? AND remaining_steps > 0 "
            "AND envelope_hash = ?",
            (task_id, expected_revision, envelope_hash),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT state_revision, remaining_steps, envelope_hash "
                "FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None or row[0] != expected_revision:
                raise StaleRevisionError(
                    f"stale revision for task {task_id}: expected {expected_revision}"
                )
            if row[2] != envelope_hash:
                raise PermitInvalidError(
                    f"envelope_hash mismatch for task {task_id}"
                )
            raise ValueError(f"budget exhausted for task {task_id}")
        new_revision = expected_revision + 1
        conn.execute(
            "INSERT INTO permits ("
            "permit_id, task_id, action_id, fingerprint, envelope_hash, "
            "state_revision, consumed) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                permit_id,
                task_id,
                action_id,
                fingerprint,
                envelope_hash,
                new_revision,
            ),
        )
        conn.execute("RELEASE SAVEPOINT sp_create_permit")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_create_permit")
        conn.execute("RELEASE SAVEPOINT sp_create_permit")
        raise
    return permit_id


def consume_permit_and_open_window(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    permit_id: str,
    expected_revision: int,
    action_kind: str,
    preimage: dict | None = None,
    postimage: dict | None = None,
    executor: Any = None,
) -> str:
    del executor
    window_id = str(uuid.uuid4())
    pre_json = json.dumps(preimage) if preimage is not None else None
    post_json = json.dumps(postimage) if postimage is not None else None
    conn.execute("SAVEPOINT sp_consume_permit")
    try:
        permit = conn.execute(
            "SELECT consumed, envelope_hash FROM permits "
            "WHERE permit_id = ? AND task_id = ?",
            (permit_id, task_id),
        ).fetchone()
        if permit is None:
            raise LookupError(f"permit {permit_id} not found for task {task_id}")
        if permit[0]:
            raise PermitConsumedError(f"permit {permit_id} already consumed")
        task = conn.execute(
            "SELECT envelope_hash FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None or task[0] != permit[1]:
            raise PermitInvalidError(
                f"envelope_hash mismatch for permit {permit_id}"
            )
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ?",
            ("executing_action", task_id, expected_revision),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        conn.execute(
            "UPDATE permits SET consumed = 1 WHERE permit_id = ? AND consumed = 0",
            (permit_id,),
        )
        conn.execute(
            "INSERT INTO execution_windows ("
            "window_id, task_id, permit_id, action_kind, status, "
            "preimage_json, postimage_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                window_id,
                task_id,
                permit_id,
                action_kind,
                "executing_action",
                pre_json,
                post_json,
            ),
        )
        conn.execute("RELEASE SAVEPOINT sp_consume_permit")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_consume_permit")
        conn.execute("RELEASE SAVEPOINT sp_consume_permit")
        raise
    return window_id
