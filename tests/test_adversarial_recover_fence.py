from __future__ import annotations

import os
from pathlib import Path

import pytest

from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import recover
from guardedcoder.persist.store import create_task


def _open_patch(conn, preimage: dict, postimage: dict) -> str:
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


def _task(conn):
    conn.row_factory = __import__("sqlite3").Row
    return conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()


def test_recover_escape_path_is_error_without_outside_read(tmp_path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("OUTSIDE-BODY", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "inside.txt").write_text("in", encoding="utf-8")
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(ws.resolve()),
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    _open_patch(
        conn,
        preimage={"inside.txt": "in"},
        postimage={"../secret.txt": "OUTSIDE-BODY"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "error"
    assert (ws / "inside.txt").read_text(encoding="utf-8") == "in"


def test_recover_rejects_workspace_not_owned_by_task(tmp_path) -> None:
    ws = tmp_path / "ws"
    other = tmp_path / "other"
    ws.mkdir()
    other.mkdir()
    (ws / "a.txt").write_text("after", encoding="utf-8")
    (other / "a.txt").write_text("after", encoding="utf-8")
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(ws.resolve()),
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    _open_patch(conn, preimage={"a.txt": "before"}, postimage={"a.txt": "after"})
    recover(conn, task_id="t1", workspace=other, expected_revision=3)
    assert _task(conn)["run_state"] == "error"


def test_recover_symlink_escape_is_error(tmp_path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("LINK-BODY", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    link = ws / "escape"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Windows cannot create symlink")
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(ws.resolve()),
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=10,
    )
    _open_patch(
        conn,
        preimage={"escape": "LINK-BODY"},
        postimage={"escape": "LINK-BODY"},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "error"
