from __future__ import annotations

import json
import sqlite3

import pytest

from guardedcoder.errors import PermitConsumedError, StaleRevisionError
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.store import create_task


class SpyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *args: object, **kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("executor must not be invoked")


def _create(conn: sqlite3.Connection, *, remaining_steps: int = 10) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=remaining_steps,
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def test_create_permit_decrements_remaining_steps(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    spy = SpyExecutor()
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
        executor=spy,
    )
    task = _task(conn)
    assert task["remaining_steps"] == 9
    assert task["state_revision"] == 2
    row = conn.execute(
        "SELECT * FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()
    assert row["consumed"] == 0
    assert row["action_id"] == "a1"
    assert row["fingerprint"] == "fp1"
    assert row["envelope_hash"] == "env-1"
    assert row["task_id"] == "t1"
    assert spy.calls == 0


def test_create_and_consume_never_call_executor(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    spy = SpyExecutor()
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
        executor=spy,
    )
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="run_command",
        executor=spy,
    )
    assert spy.calls == 0


def test_consume_opens_window_and_sets_executing_action(tmp_path) -> None:
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
    window_id = consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="apply_patch",
        preimage={"a": 1},
        postimage=None,
    )
    task = _task(conn)
    assert task["run_state"] == "executing_action"
    assert task["state_revision"] == 3
    permit = conn.execute(
        "SELECT consumed FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()
    assert permit[0] == 1
    win = conn.execute(
        "SELECT * FROM execution_windows WHERE window_id = ?", (window_id,)
    ).fetchone()
    assert win["permit_id"] == permit_id
    assert win["action_kind"] == "apply_patch"
    assert win["status"] == "executing_action"
    assert json.loads(win["preimage_json"]) == {"a": 1}
    assert win["postimage_json"] is None


def test_second_consume_raises_permit_consumed(tmp_path) -> None:
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
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="run_command",
    )
    before = dict(_task(conn))
    windows = conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0]
    with pytest.raises(PermitConsumedError):
        consume_permit_and_open_window(
            conn,
            task_id="t1",
            permit_id=permit_id,
            expected_revision=3,
            action_kind="run_command",
        )
    after = dict(_task(conn))
    assert after == before
    assert conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0] == windows


def test_stale_revision_create_no_side_effects(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn)
    before = dict(_task(conn))
    with pytest.raises(StaleRevisionError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp1",
            envelope_hash="env-1",
            expected_revision=99,
        )
    assert dict(_task(conn)) == before
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0


def test_stale_revision_consume_no_side_effects(tmp_path) -> None:
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
    before_task = dict(_task(conn))
    with pytest.raises(StaleRevisionError):
        consume_permit_and_open_window(
            conn,
            task_id="t1",
            permit_id=permit_id,
            expected_revision=99,
            action_kind="run_command",
        )
    assert dict(_task(conn)) == before_task
    consumed = conn.execute(
        "SELECT consumed FROM permits WHERE permit_id = ?", (permit_id,)
    ).fetchone()[0]
    assert consumed == 0
    assert conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0] == 0


def test_second_unconsumed_permit_integrity_error(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn, remaining_steps=5)
    create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    remaining = _task(conn)["remaining_steps"]
    with pytest.raises(sqlite3.IntegrityError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a2",
            fingerprint="fp2",
            envelope_hash="env-1",
            expected_revision=2,
        )
    assert _task(conn)["remaining_steps"] == remaining
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 1


def test_create_permit_fails_when_budget_exhausted(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    _create(conn, remaining_steps=0)
    with pytest.raises(ValueError):
        create_permit(
            conn,
            task_id="t1",
            action_id="a1",
            fingerprint="fp1",
            envelope_hash="env-1",
            expected_revision=1,
        )
    assert _task(conn)["remaining_steps"] == 0
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
