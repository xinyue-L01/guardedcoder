from __future__ import annotations

import json
import re
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


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _norm_key(rel: str) -> str:
    text = rel.replace("\\", "/").strip()
    if not text or text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise PermitInvalidError(f"illegal image path {rel!r}")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PermitInvalidError(f"illegal image path {rel!r}")
    return "/".join(parts)


def _parse_marks(image: dict) -> dict[str, dict[str, object]]:
    stored: dict[str, dict[str, object]] = {}
    for rel, value in image.items():
        if not isinstance(value, dict) or "exists" not in value or "sha256" not in value:
            raise PermitInvalidError("preimage/postimage must be {exists, sha256} marks")
        exists = value["exists"]
        if exists is not True and exists is not False:
            raise PermitInvalidError("exists must be a real bool")
        digest = value["sha256"]
        if exists is True:
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                raise PermitInvalidError("sha256 mark must be 64 lowercase hex chars")
        elif digest is not None:
            raise PermitInvalidError("missing file mark must use sha256=null")
        if not isinstance(rel, str):
            raise PermitInvalidError(f"illegal image path {rel!r}")
        key = _norm_key(rel)
        if key in stored:
            raise PermitInvalidError(f"duplicate image path {rel!r}")
        stored[key] = {"exists": exists, "sha256": digest}
    return stored


def _store_images(
    action_kind: str,
    preimage: dict | None,
    postimage: dict | None,
) -> tuple[str | None, str | None]:
    if action_kind == "apply_patch":
        if not preimage or not postimage:
            raise PermitInvalidError("apply_patch requires non-empty preimage and postimage")
        pre_marks = _parse_marks(preimage)
        post_marks = _parse_marks(postimage)
        if not pre_marks or set(pre_marks) != set(post_marks):
            raise PermitInvalidError("preimage/postimage path sets must be identical")
        return json.dumps(pre_marks, ensure_ascii=False), json.dumps(
            post_marks, ensure_ascii=False
        )
    pre_json = json.dumps(_parse_marks(preimage), ensure_ascii=False) if preimage else None
    post_json = json.dumps(_parse_marks(postimage), ensure_ascii=False) if postimage else None
    return pre_json, post_json


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
        if task[0] not in {"running", "verifying", "awaiting_approval"}:
            raise PermitInvalidError(
                f"cannot create permit from run_state {task[0]!r}"
            )
        if task[0] in {"executing_action", "applying"} or _active_window(conn, task_id):
            raise ExecutionWindowOpenError(
                f"task {task_id} already has an active execution window"
            )
        if task[2] <= 0:
            raise ValueError(f"budget exhausted for task {task_id}")
        if task[0] == "awaiting_approval" and pending_action_id is None:
            raise PermitInvalidError(
                "awaiting_approval requires a consumed pending_action_id"
            )
        if pending_action_id is not None:
            pending = conn.execute(
                "SELECT task_id, consumed, fingerprint, state_revision "
                "FROM pending_actions WHERE pending_action_id = ?",
                (pending_action_id,),
            ).fetchone()
            if (
                pending is None
                or pending[0] != task_id
                or not pending[1]
                or pending[2] != fingerprint
                or pending[3] != expected_revision
            ):
                raise PermitInvalidError(
                    f"pending_action_id {pending_action_id} does not match "
                    f"consumed pending fingerprint for task {task_id}"
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
    pre_json, post_json = _store_images(action_kind, preimage, postimage)
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
        source_run_state = task[2]
        new_run_state = (
            "verifying" if source_run_state == "verifying" else "executing_action"
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
            "preimage_json, postimage_json, opened_revision, source_run_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                window_id,
                task_id,
                permit_id,
                action_kind,
                "executing_action",
                pre_json,
                post_json,
                expected_revision + 1,
                source_run_state,
            ),
        )
    return window_id
