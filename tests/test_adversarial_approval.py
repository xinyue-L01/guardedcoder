from __future__ import annotations

import threading

import pytest

from guardedcoder.errors import ApprovalError, PendingConsumedError
from guardedcoder.persist.approval import approve, insert_pending
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task, update_task


def _setup(path) -> str:
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
    return pending_id


def test_two_connections_only_one_approve_succeeds(tmp_path) -> None:
    path = tmp_path / "g.db"
    pending_id = _setup(path)
    results: list[object] = []

    def worker() -> None:
        conn = connect(path)
        try:
            results.append(approve(conn, "t1", "fp-1"))
        except (PendingConsumedError, ApprovalError) as exc:
            results.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    oks = [item for item in results if item == pending_id]
    fails = [item for item in results if isinstance(item, Exception)]
    assert len(oks) == 1
    assert len(fails) == 1
    conn = connect(path)
    consumed = conn.execute(
        "SELECT consumed FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()[0]
    assert consumed == 1
    conn.close()


def test_task_revision_change_blocks_old_approval(tmp_path) -> None:
    path = tmp_path / "g.db"
    pending_id = _setup(path)
    conn = connect(path)
    update_task(conn, "t1", 1, run_state="awaiting_approval")
    with pytest.raises(ApprovalError):
        approve(conn, "t1", "fp-1")
    consumed = conn.execute(
        "SELECT consumed FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()[0]
    assert consumed == 0
    conn.close()
