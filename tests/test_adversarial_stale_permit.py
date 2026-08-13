from __future__ import annotations

import sqlite3

import pytest

from guardedcoder.errors import PermitInvalidError, StaleRevisionError
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.store import create_task, update_task


def _create(conn: sqlite3.Connection) -> None:
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


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def test_stale_permit_not_consumed_after_revision_change_same_envelope(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    update_task(conn, "t1", 2, run_state="running")
    task = _task(conn)
    assert task["envelope_hash"] == "env-1"
    assert task["state_revision"] == 3
    remaining = task["remaining_steps"]
    with pytest.raises((PermitInvalidError, StaleRevisionError)):
        consume_permit_and_open_window(
            conn,
            task_id="t1",
            permit_id=permit_id,
            expected_revision=3,
            action_kind="run_command",
        )
    after = _task(conn)
    assert after["remaining_steps"] == remaining
    consumed = conn.execute(
        "SELECT consumed FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()[0]
    assert consumed == 0
    assert conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0] == 0
    with pytest.raises((sqlite3.IntegrityError, PermitInvalidError, StaleRevisionError)):
        create_permit(
            conn,
            task_id="t1",
            action_id="a2",
            fingerprint="fp2",
            envelope_hash="env-1",
            expected_revision=3,
        )
    assert _task(conn)["remaining_steps"] == remaining
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 1
