from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from guardedcoder.errors import (
    ExecutionWindowOpenError,
    PermitConsumedError,
    PermitInvalidError,
    StaleRevisionError,
)
from guardedcoder.persist.txn import write_txn


def _store_image(image: dict | None) -> str | None:
    if image is None:
        return None
    stored: dict[str, dict[str, object]] = {}
    for rel, value in image.items():
        if isinstance(value, dict) and "exists" in value:
            stored[rel] = {
                "exists": bool(value["exists"]),
                "sha256": value.get("sha256"),
            }
        elif isinstance(value, str):
            stored[rel] = {
                "exists": True,
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        else:
            raise PermitInvalidError("preimage/postimage entries must be marks or text")
    return json.dumps(stored, ensure_ascii=False)


def _active_window(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM execution_windows WHERE task_id = ? "
        "AND status IN ('executing_action', 'applying')",
        (task_id,),
    ).fetchone()
    return row is not None


def create_permit(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    action_id: str,
    fingerprint: str,
    envelope_hash: str,
    expected_revision: int,
    pending_action_id: str | None = None,
    executor: Any = None,
) -> str:
    del executor
    permit_id = str(uuid.uuid4())
    with write_txn(conn):
        task = conn.execute(
            "SELECT run_state, state_revision, remaining_steps, envelope_hash "
            "FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None or task[1] != expected_revision:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        if task[3] != envelope_hash:
            raise PermitInvalidError(f"envelope_hash mismatch for task {task_id}")
        if task[0] in {"executing_action", "applying"} or _active_window(conn, task_id):
            raise ExecutionWindowOpenError(
                f"task {task_id} already has an active execution window"
            )
        if task[2] <= 0:
            raise ValueError(f"budget exhausted for task {task_id}")
        if pending_action_id is not None:
            pending = conn.execute(
                "SELECT task_id, consumed FROM pending_actions "
                "WHERE pending_action_id = ?",
                (pending_action_id,),
            ).fetchone()
            if pending is None or pending[0] != task_id or not pending[1]:
                raise PermitInvalidError(
                    f"pending_action_id {pending_action_id} is not a consumed "
                    f"pending action for task {task_id}"
                )
        cur = conn.execute(
            "UPDATE tasks SET remaining_steps = remaining_steps - 1, "
            "state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ? AND remaining_steps > 0 "
            "AND envelope_hash = ?",
            (task_id, expected_revision, envelope_hash),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        new_revision = expected_revision + 1
        conn.execute(
            "INSERT INTO permits ("
            "permit_id, task_id, action_id, fingerprint, envelope_hash, "
            "state_revision, consumed, pending_action_id) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (
                permit_id,
                task_id,
                action_id,
                fingerprint,
                envelope_hash,
                new_revision,
                pending_action_id,
            ),
        )
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
    pre_json = _store_image(preimage)
    post_json = _store_image(postimage)
    with write_txn(conn):
        permit = conn.execute(
            "SELECT consumed, envelope_hash, state_revision, task_id "
            "FROM permits WHERE permit_id = ?",
            (permit_id,),
        ).fetchone()
        if permit is None or permit[3] != task_id:
            raise LookupError(f"permit {permit_id} not found for task {task_id}")
        if permit[0]:
            raise PermitConsumedError(f"permit {permit_id} already consumed")
        task = conn.execute(
            "SELECT envelope_hash, state_revision, run_state FROM tasks "
            "WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise PermitInvalidError(f"task {task_id} not found")
        if (
            permit[1] != task[0]
            or permit[2] != task[1]
            or task[1] != expected_revision
        ):
            raise PermitInvalidError(
                f"permit {permit_id} context does not match task {task_id}"
            )
        if _active_window(conn, task_id):
            raise ExecutionWindowOpenError(
                f"task {task_id} already has an active execution window"
            )
        new_run_state = (
            "verifying" if task[2] == "verifying" else "executing_action"
        )
        cur = conn.execute(
            "UPDATE permits SET consumed = 1 WHERE permit_id = ? AND consumed = 0 "
            "AND task_id = ? AND state_revision = ? AND envelope_hash = ?",
            (permit_id, task_id, expected_revision, task[0]),
        )
        if cur.rowcount != 1:
            raise PermitConsumedError(f"permit {permit_id} already consumed")
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ? AND envelope_hash = ?",
            (new_run_state, task_id, expected_revision, task[0]),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
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
    return window_id
