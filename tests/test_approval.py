from __future__ import annotations

import inspect
import sqlite3

import pytest

from guardedcoder.errors import ApprovalError, PendingConsumedError
from guardedcoder.persist.approval import approve, insert_pending
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task, update_task


def _create(conn: sqlite3.Connection, *, envelope_hash: str = "env-1") -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash=envelope_hash,
        remaining_steps=10,
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def _pending(conn: sqlite3.Connection, pending_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()
    assert row is not None
    return row


def test_approve_requires_fingerprint_parameter() -> None:
    sig = inspect.signature(approve)
    assert "fingerprint" in sig.parameters
    assert sig.parameters["fingerprint"].default is inspect.Parameter.empty
    params = list(sig.parameters)
    assert params[-2:] == ["task_id", "fingerprint"] or (
        "task_id" in params and "fingerprint" in params
    )


def test_approve_consumes_once_and_binds(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-env-1",
        normalized_action_json='{"tool":"apply_patch"}',
        state_revision=1,
    )
    returned = approve(conn, "t1", "fp-env-1")
    assert returned == pending_id
    row = _pending(conn, pending_id)
    assert row["consumed"] == 1
    assert row["fingerprint"] == "fp-env-1"
    assert row["state_revision"] == 1
    assert row["task_id"] == "t1"
    assert _task(conn)["run_state"] == "awaiting_approval"


def test_wrong_fingerprint_raises_and_does_not_consume(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-env-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    with pytest.raises(ApprovalError):
        approve(conn, "t1", "wrong-fp")
    assert _pending(conn, pending_id)["consumed"] == 0


def test_second_consume_raises(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-env-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    approve(conn, "t1", "fp-env-1")
    with pytest.raises(PendingConsumedError):
        approve(conn, "t1", "fp-env-1")
    assert _pending(conn, pending_id)["consumed"] == 1


def test_envelope_hash_change_invalidates_old_fingerprint(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn, envelope_hash="env-1")
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-env-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    update_task(conn, "t1", 1, envelope_hash="env-2")
    assert _task(conn)["state_revision"] == 2
    assert _task(conn)["envelope_hash"] == "env-2"
    with pytest.raises(ApprovalError):
        approve(conn, "t1", "fp-env-1")
    assert _pending(conn, pending_id)["consumed"] == 0
