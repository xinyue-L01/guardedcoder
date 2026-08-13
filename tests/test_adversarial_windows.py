from __future__ import annotations

import sqlite3

import pytest

from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.store import create_task


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


def test_no_second_permit_or_window_while_executing_action(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    first = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=first,
        expected_revision=2,
        action_kind="run_command",
    )
    remaining = _task(conn)["remaining_steps"]
    windows = conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0]
    assert windows == 1
    with pytest.raises(Exception):
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
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO execution_windows ("
            "window_id, task_id, permit_id, action_kind, status, "
            "preimage_json, postimage_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("w2", "t1", first, "run_command", "executing_action", None, None),
        )
    assert conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0] == 1
