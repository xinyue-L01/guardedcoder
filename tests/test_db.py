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


def test_migration_preserves_recovery_claims_and_makes_permit_nullable(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-f.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, run_state TEXT NOT NULL,
            artifact_state TEXT NOT NULL, repo_path TEXT NOT NULL,
            base_commit TEXT NOT NULL, worktree_identity TEXT NOT NULL,
            envelope_hash TEXT NOT NULL, state_revision INTEGER NOT NULL,
            remaining_steps INTEGER NOT NULL
        );
        CREATE TABLE permits (
            permit_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
            action_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            envelope_hash TEXT NOT NULL, state_revision INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0, pending_action_id TEXT
        );
        CREATE TABLE execution_windows (
            window_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
            permit_id TEXT NOT NULL REFERENCES permits(permit_id),
            action_kind TEXT NOT NULL, status TEXT NOT NULL,
            preimage_json TEXT, postimage_json TEXT,
            opened_revision INTEGER NOT NULL, source_run_state TEXT NOT NULL,
            execution_started INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE recovered_attempt_claims (
            claim_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
            window_id TEXT NOT NULL REFERENCES execution_windows(window_id),
            state_revision INTEGER NOT NULL, attempt_id TEXT NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX idx_recovered_claim_exclusive
            ON recovered_attempt_claims(task_id, window_id, state_revision);
        INSERT INTO tasks VALUES
            ('t1', 'running', 'worktree_present', '/repo', 'abc', 'wt', 'env', 1, 4);
        INSERT INTO permits VALUES ('p1', 't1', 'a1', 'fp', 'env', 1, 1, NULL);
        INSERT INTO execution_windows VALUES
            ('w1', 't1', 'p1', 'run_command', 'executing_action', NULL, NULL, 1,
             'running', 1);
        INSERT INTO recovered_attempt_claims VALUES ('c1', 't1', 'w1', 1, 'a1', 0);
        """
    )
    legacy.commit()
    legacy.close()

    conn = connect(path)
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(execution_windows)")}
    assert columns["permit_id"][3] == 0
    assert {"fingerprint", "execution_started"} <= columns.keys()
    assert conn.execute("SELECT claim_id FROM recovered_attempt_claims").fetchone() == (
        "c1",
    )
    assert list(conn.execute("PRAGMA foreign_key_check")) == []
