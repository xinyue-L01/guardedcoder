from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from guardedcoder.errors import StaleRevisionError
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import recover
from guardedcoder.persist.store import create_task


class SpyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *args: object, **kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("executor must not be invoked")


def _create(conn: sqlite3.Connection, workspace: Path) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash="env-1",
        remaining_steps=10,
    )


def _open_command_window(conn: sqlite3.Connection) -> str:
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    return consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="run_command",
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def _window(conn: sqlite3.Connection, window_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM execution_windows WHERE window_id = ?", (window_id,)
    ).fetchone()
    assert row is not None
    return row


def test_run_command_executing_action_sets_error_without_execute(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_command_window(conn)
    spy = SpyExecutor()
    recover(
        conn,
        task_id="t1",
        workspace=ws,
        expected_revision=3,
        executor=spy,
    )
    task = _task(conn)
    assert task["run_state"] == "error"
    assert task["state_revision"] == 4
    assert _window(conn, window_id)["status"] == "error"
    assert spy.calls == 0


def test_run_command_stale_revision_no_db_change_and_no_execute(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_command_window(conn)
    spy = SpyExecutor()
    before_task = dict(_task(conn))
    before_win = dict(_window(conn, window_id))
    with pytest.raises(StaleRevisionError):
        recover(
            conn,
            task_id="t1",
            workspace=ws,
            expected_revision=99,
            executor=spy,
        )
    assert dict(_task(conn)) == before_task
    assert dict(_window(conn, window_id)) == before_win
    assert spy.calls == 0
