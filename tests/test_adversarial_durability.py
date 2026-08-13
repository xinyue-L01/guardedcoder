from __future__ import annotations

from guardedcoder.persist.approval import approve, insert_pending
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task


def test_create_task_survives_reconnect(tmp_path) -> None:
    path = tmp_path / "g.db"
    conn = connect(path)
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=4,
    )
    conn.close()
    conn2 = connect(path)
    row = conn2.execute("SELECT task_id FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    conn2.close()


def test_insert_pending_survives_reconnect(tmp_path) -> None:
    path = tmp_path / "g.db"
    conn = connect(path)
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=4,
    )
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    conn.close()
    conn2 = connect(path)
    row = conn2.execute(
        "SELECT pending_action_id FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()
    assert row is not None
    conn2.close()


def test_approve_consumed_survives_reconnect(tmp_path) -> None:
    path = tmp_path / "g.db"
    conn = connect(path)
    create_task(
        conn,
        task_id="t1",
        run_state="awaiting_approval",
        artifact_state="worktree_present",
        repo_path="/repo",
        base_commit="abc",
        worktree_identity="wt-1",
        envelope_hash="env-1",
        remaining_steps=4,
    )
    pending_id = insert_pending(
        conn,
        task_id="t1",
        fingerprint="fp-1",
        normalized_action_json="{}",
        state_revision=1,
    )
    approve(conn, "t1", "fp-1")
    conn.close()
    conn2 = connect(path)
    consumed = conn2.execute(
        "SELECT consumed FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()[0]
    assert consumed == 1
    conn2.close()
