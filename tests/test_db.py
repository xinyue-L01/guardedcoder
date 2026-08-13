from __future__ import annotations

import sqlite3

import pytest

from guardedcoder.errors import StaleRevisionError
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task, update_task


def _create(conn: sqlite3.Connection, task_id: str = "t1") -> None:
    create_task(
        conn,
        task_id=task_id,
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )


def _row(conn: sqlite3.Connection, task_id: str = "t1") -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    row = cur.fetchone()
    assert row is not None
    return row


def test_connect_enables_foreign_keys(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1


def test_foreign_keys_reject_orphan_audit(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO audit_events (event_id, task_id, payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("e1", "missing", "{}", "now"),
        )


def test_create_task_revision_one(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    row = _row(conn)
    assert row["state_revision"] == 1
    assert row["remaining_steps"] == 10


def test_update_task_stale_revision_unchanged(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    before = dict(_row(conn))
    with pytest.raises(StaleRevisionError):
        update_task(conn, "t1", expected_revision=99, remaining_steps=1)
    after = dict(_row(conn))
    assert after == before


def test_update_task_success_bumps_revision(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    update_task(conn, "t1", expected_revision=1, remaining_steps=7)
    row = _row(conn)
    assert row["remaining_steps"] == 7
    assert row["state_revision"] == 2


def test_one_unconsumed_pending_action_per_task(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    conn.execute(
        "INSERT INTO pending_actions "
        "(pending_action_id, task_id, fingerprint, normalized_action_json, "
        "state_revision, consumed) VALUES (?, ?, ?, ?, ?, 0)",
        ("p1", "t1", "fp", "{}", 1),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pending_actions "
            "(pending_action_id, task_id, fingerprint, normalized_action_json, "
            "state_revision, consumed) VALUES (?, ?, ?, ?, ?, 0)",
            ("p2", "t1", "fp2", "{}", 1),
        )


def test_one_unconsumed_permit_per_task(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    conn.execute(
        "INSERT INTO permits "
        "(permit_id, task_id, action_id, fingerprint, envelope_hash, "
        "state_revision, consumed) VALUES (?, ?, ?, ?, ?, ?, 0)",
        ("perm1", "t1", "a1", "fp", "env-1", 1),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO permits "
            "(permit_id, task_id, action_id, fingerprint, envelope_hash, "
            "state_revision, consumed) VALUES (?, ?, ?, ?, ?, ?, 0)",
            ("perm2", "t1", "a2", "fp2", "env-1", 1),
        )
