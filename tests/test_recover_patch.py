from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from guardedcoder.errors import StaleRevisionError
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import recover
from guardedcoder.persist.store import create_task


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create(conn: sqlite3.Connection, workspace: Path) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )


def _open_patch_window(
    conn: sqlite3.Connection,
    *,
    preimage: dict[str, str],
    postimage: dict[str, str],
) -> str:
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
        action_kind="apply_patch",
        preimage=preimage,
        postimage=postimage,
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


def test_all_postimage_records_success_running(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "after-a")
    _write(ws, "b.txt", "after-b")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_patch_window(
        conn,
        preimage={"a.txt": "before-a", "b.txt": "before-b"},
        postimage={"a.txt": "after-a", "b.txt": "after-b"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    task = _task(conn)
    assert task["run_state"] == "running"
    assert task["state_revision"] == 4
    assert _window(conn, window_id)["status"] == "succeeded"


def test_all_preimage_stays_recoverable(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "before-a")
    _write(ws, "b.txt", "before-b")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_patch_window(
        conn,
        preimage={"a.txt": "before-a", "b.txt": "before-b"},
        postimage={"a.txt": "after-a", "b.txt": "after-b"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    task = _task(conn)
    assert task["run_state"] == "executing_action"
    assert task["state_revision"] == 3
    assert _window(conn, window_id)["status"] == "executing_action"


def test_mixed_sets_run_state_error(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "after-a")
    _write(ws, "b.txt", "before-b")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_patch_window(
        conn,
        preimage={"a.txt": "before-a", "b.txt": "before-b"},
        postimage={"a.txt": "after-a", "b.txt": "after-b"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    task = _task(conn)
    assert task["run_state"] == "error"
    assert task["state_revision"] == 4
    assert _window(conn, window_id)["status"] == "error"


def test_neither_pre_nor_post_is_error(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "other")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _open_patch_window(
        conn,
        preimage={"a.txt": "before"},
        postimage={"a.txt": "after"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "error"


def test_does_not_rewrite_workspace_files(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "before")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _open_patch_window(
        conn,
        preimage={"a.txt": "before"},
        postimage={"a.txt": "after"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert (ws / "a.txt").read_text(encoding="utf-8") == "before"


def test_stale_revision_no_db_change_on_success_path(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write(ws, "a.txt", "after")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open_patch_window(
        conn,
        preimage={"a.txt": "before"},
        postimage={"a.txt": "after"},
    )
    before_task = dict(_task(conn))
    before_win = dict(_window(conn, window_id))
    with pytest.raises(StaleRevisionError):
        recover(conn, task_id="t1", workspace=ws, expected_revision=99)
    assert dict(_task(conn)) == before_task
    assert dict(_window(conn, window_id)) == before_win
    assert (ws / "a.txt").read_text(encoding="utf-8") == "after"


def test_run_command_not_implemented(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
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
        action_kind="run_command",
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "error"
    assert _window(conn, window_id)["status"] == "error"
