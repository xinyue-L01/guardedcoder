from __future__ import annotations

import sqlite3

import pytest

from guardedcoder.errors import PermitInvalidError
from guardedcoder.persist.approval import approve, insert_pending
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.store import create_task, update_task


def _task(conn: sqlite3.Connection, task_id: str = "t1") -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    assert row is not None
    return row


def test_consume_compares_permit_and_task_revision_and_envelope(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    row = conn.execute(
        "SELECT state_revision, envelope_hash, task_id FROM permits WHERE permit_id = ?",
        (permit_id,),
    ).fetchone()
    assert row[0] == _task(conn)["state_revision"]
    assert row[1] == _task(conn)["envelope_hash"]
    assert row[2] == "t1"
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=row[0],
        action_kind="run_command",
    )


def test_auto_permit_pending_action_id_is_null(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
        pending_action_id=None,
    )
    value = conn.execute(
        "SELECT pending_action_id FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()[0]
    assert value is None


def test_approval_permit_must_match_consumed_pending(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp-1",
            envelope_hash="env-1",
            expected_revision=1,
            pending_action_id=pending_id,
        )
    approve(conn, "t1", "fp-1")
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp-other",
            envelope_hash="env-1",
            expected_revision=1,
            pending_action_id=pending_id,
        )
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp-1",
        envelope_hash="env-1",
        expected_revision=1,
        pending_action_id=pending_id,
    )
    bound = conn.execute(
        "SELECT pending_action_id FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()[0]
    assert bound == pending_id
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a2",
            fingerprint="fp-2",
            envelope_hash="env-1",
            expected_revision=2,
            pending_action_id="missing-pending",
        )


def test_consumed_pending_cannot_issue_permit_after_revision_bump(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    approve(conn, "t1", "fp-1")
    update_task(conn, "t1", 1, envelope_hash="env-2")
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp-1",
            envelope_hash="env-2",
            expected_revision=2,
            pending_action_id=pending_id,
        )


def test_verifying_window_does_not_set_executing_action(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="verifying",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="verify",
        fingerprint="fp-v",
        envelope_hash="env-1",
        expected_revision=1,
    )
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="run_command",
    )
    assert _task(conn)["run_state"] == "verifying"
    status = conn.execute(
        "SELECT status FROM execution_windows WHERE task_id = ?", ("t1",)
    ).fetchone()[0]
    assert status == "executing_action"


def test_awaiting_approval_rejects_auto_permit(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp-1",
            envelope_hash="env-1",
            expected_revision=1,
        )


def test_succeeded_rejects_new_permit(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="succeeded",
        artifact_state="patch_ready",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    with pytest.raises(PermitInvalidError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp-1",
            envelope_hash="env-1",
            expected_revision=1,
        )
