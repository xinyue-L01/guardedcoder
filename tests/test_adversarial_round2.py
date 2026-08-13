from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from guardedcoder.errors import ApprovalError, PermitInvalidError, StaleRevisionError
from guardedcoder.persist.approval import approve, insert_pending, request_approval
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.persist.store import create_task, update_task


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mark(*, exists: bool, body: bytes | None = None) -> dict:
    if not exists:
        return {"exists": False, "sha256": None}
    assert body is not None
    return {"exists": True, "sha256": _sha(body)}


def _create_ws(conn: sqlite3.Connection, workspace: Path) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path="/orig-repo",
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash="env-1",
        remaining_steps=10,
    )


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


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()


def _window(conn: sqlite3.Connection, window_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM execution_windows WHERE window_id = ?", (window_id,)
    ).fetchone()


class SpyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *args: object, **kwargs: object) -> None:
        self.calls += 1


def test_disjoint_pre_post_keys_never_succeed(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b.txt").write_bytes(b"after-b")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    with pytest.raises(PermitInvalidError):
        _open_patch(
            conn,
            preimage={"a.txt": _mark(exists=True, body=b"old-a")},
            postimage={"b.txt": _mark(exists=True, body=b"after-b")},
        )
    permit_id = conn.execute("SELECT permit_id FROM permits").fetchone()[0]
    conn.execute("UPDATE permits SET consumed = 1 WHERE permit_id = ?", (permit_id,))
    conn.execute(
        "UPDATE tasks SET run_state = 'executing_action', state_revision = 3 "
        "WHERE task_id = 't1'"
    )
    conn.execute(
        "INSERT INTO execution_windows ("
        "window_id, task_id, permit_id, action_kind, status, "
        "preimage_json, postimage_json, opened_revision, source_run_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "w-bad",
            "t1",
            permit_id,
            "apply_patch",
            "executing_action",
            '{"a.txt":{"exists":true,"sha256":"%s"}}' % _sha(b"old-a"),
            '{"b.txt":{"exists":true,"sha256":"%s"}}' % _sha(b"after-b"),
            3,
            "running",
        ),
    )
    decision = recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert decision == RecoverDecision.recorded_error
    assert _task(conn)["run_state"] == "error"
    assert _window(conn, "w-bad")["status"] == "error"


def test_preimage_recover_does_not_reclaim_at_new_revision(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    window_id = _open_patch(
        conn,
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    first = recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert first == RecoverDecision.retryable_same_attempt
    before = dict(_task(conn))
    assert before["state_revision"] == 3
    assert before["run_state"] == "executing_action"
    update_task(conn, "t1", 3, remaining_steps=9)
    assert _task(conn)["state_revision"] == 4
    second = recover(conn, task_id="t1", workspace=ws, expected_revision=4)
    assert second != RecoverDecision.retryable_same_attempt
    assert second != RecoverDecision.recorded_success
    assert _task(conn)["run_state"] == "error"
    assert _window(conn, window_id)["status"] == "error"


def test_recover_does_not_revive_succeeded_task(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    window_id = _open_patch(
        conn,
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    update_task(conn, "t1", 3, run_state="succeeded")
    assert _task(conn)["run_state"] == "succeeded"
    recover(conn, task_id="t1", workspace=ws, expected_revision=4)
    assert _task(conn)["run_state"] == "error"
    assert _window(conn, window_id)["status"] == "error"


def test_insert_pending_stale_revision_leaves_no_row(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
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
    with pytest.raises((StaleRevisionError, ApprovalError)):
        insert_pending(
            conn,
            task_id="t1",
            fingerprint="fp-1",
            normalized_action_json="{}",
            state_revision=999,
        )
    assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0


def test_exists_rejects_truthy_string(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    fake = {"exists": "false", "sha256": None}
    with pytest.raises(PermitInvalidError):
        consume_permit_and_open_window(
            conn,
            task_id="t1",
            permit_id=permit_id,
            expected_revision=2,
            action_kind="apply_patch",
            preimage={"a.txt": fake},
            postimage={"a.txt": fake},
        )


def test_create_modify_delete_share_path_set(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "f.txt").write_bytes(b"new")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    _open_patch(
        conn,
        preimage={"f.txt": _mark(exists=False)},
        postimage={"f.txt": _mark(exists=True, body=b"new")},
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_success
    )


def test_concurrent_recover_does_not_double_authorize(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before")
    path = tmp_path / "g.db"
    setup = connect(path)
    _create_ws(setup, ws)
    _open_patch(
        setup,
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    setup.close()
    spy = SpyExecutor()
    results: list[object] = []

    def worker() -> None:
        conn = connect(path)
        try:
            results.append(
                recover(
                    conn,
                    task_id="t1",
                    workspace=ws,
                    expected_revision=3,
                    executor=spy,
                )
            )
        except Exception as exc:
            results.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert spy.calls == 0
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM execution_windows").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 1
    task = _task(conn)
    assert task["run_state"] == "executing_action"
    assert task["state_revision"] == 3
    assert RecoverDecision.recorded_success not in results
    assert RecoverDecision.recorded_error not in results
    conn.close()


def test_modify_same_path_set(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "f.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    _open_patch(
        conn,
        preimage={"f.txt": _mark(exists=True, body=b"before")},
        postimage={"f.txt": _mark(exists=True, body=b"after")},
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_success
    )


def test_delete_same_path_set(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    _open_patch(
        conn,
        preimage={"f.txt": _mark(exists=True, body=b"old")},
        postimage={"f.txt": _mark(exists=False)},
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_success
    )


def test_corrupt_image_json_records_error(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    window_id = _open_patch(
        conn,
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    conn.execute(
        "UPDATE execution_windows SET postimage_json = ? WHERE window_id = ?",
        ("not-json", window_id),
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_error
    )
    assert _task(conn)["run_state"] == "error"


def test_unknown_source_run_state_records_error(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    window_id = _open_patch(
        conn,
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    conn.execute(
        "UPDATE execution_windows SET source_run_state = ? WHERE window_id = ?",
        ("succeeded", window_id),
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_error
    )
    assert _task(conn)["run_state"] == "error"


def test_request_approval_is_single_atomic_commit(tmp_path) -> None:
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
    pending_id = request_approval(
        conn,
        task_id="t1",
        fingerprint="fp-1",
        normalized_action_json="{}",
        expected_revision=1,
    )
    conn.close()
    conn2 = connect(path)
    task = conn2.execute("SELECT run_state, state_revision FROM tasks").fetchone()
    assert task[0] == "awaiting_approval"
    pending = conn2.execute(
        "SELECT consumed, state_revision FROM pending_actions WHERE pending_action_id = ?",
        (pending_id,),
    ).fetchone()
    assert pending[0] == 0
    assert pending[1] == task[1]
    conn2.close()


def test_legacy_window_columns_migrate_without_indexerror(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after")
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            run_state TEXT NOT NULL,
            artifact_state TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            base_commit TEXT NOT NULL,
            worktree_identity TEXT NOT NULL,
            envelope_hash TEXT NOT NULL,
            state_revision INTEGER NOT NULL,
            remaining_steps INTEGER NOT NULL
        );
        CREATE TABLE permits (
            permit_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            action_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            envelope_hash TEXT NOT NULL,
            state_revision INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0,
            pending_action_id TEXT
        );
        CREATE TABLE execution_windows (
            window_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            permit_id TEXT NOT NULL REFERENCES permits(permit_id),
            action_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            preimage_json TEXT,
            postimage_json TEXT
        );
        """
    )
    raw.execute(
        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "t1",
            "executing_action",
            "worktree_present",
            "/orig-repo",
            "abc",
            str(ws.resolve()),
            "env-1",
            3,
            9,
        ),
    )
    raw.execute(
        "INSERT INTO permits VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("p1", "t1", "a1", "fp1", "env-1", 2, 1, None),
    )
    pre = json.dumps({"a.txt": {"exists": True, "sha256": _sha(b"before")}})
    post = json.dumps({"a.txt": {"exists": True, "sha256": _sha(b"after")}})
    raw.execute(
        "INSERT INTO execution_windows VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("w1", "t1", "p1", "apply_patch", "executing_action", pre, post),
    )
    raw.commit()
    raw.close()
    conn = connect(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(execution_windows)")}
    assert "opened_revision" in cols
    assert "source_run_state" in cols
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=3) == (
        RecoverDecision.recorded_error
    )
    assert _task(conn)["run_state"] == "error"


def test_hitl_postimage_recover_records_success(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    pending_id = request_approval(
        conn,
        task_id="t1",
        fingerprint="fp1",
        normalized_action_json="{}",
        expected_revision=1,
    )
    approve(conn, "t1", "fp1")
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=2,
        pending_action_id=pending_id,
    )
    consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=3,
        action_kind="apply_patch",
        preimage={"a.txt": _mark(exists=True, body=b"before")},
        postimage={"a.txt": _mark(exists=True, body=b"after")},
    )
    assert recover(conn, task_id="t1", workspace=ws, expected_revision=4) == (
        RecoverDecision.recorded_success
    )
    assert _task(conn)["run_state"] == "running"


def test_normalized_duplicate_image_keys_rejected(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create_ws(conn, ws)
    with pytest.raises(PermitInvalidError):
        _open_patch(
            conn,
            preimage={"a.txt": _mark(exists=True, body=b"before")},
            postimage={
                "a.txt": _mark(exists=True, body=b"after"),
                "./a.txt": _mark(exists=True, body=b"before"),
            },
        )


def test_update_task_cannot_enter_awaiting_approval(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
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
    with pytest.raises(ApprovalError):
        update_task(conn, "t1", 1, run_state="awaiting_approval")
    assert _task(conn)["run_state"] == "running"
    assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0
