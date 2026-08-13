from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import recover
from guardedcoder.persist.store import create_task


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mark(*, exists: bool, body: bytes | None = None) -> dict:
    if not exists:
        return {"exists": False, "sha256": None}
    assert body is not None
    return {"exists": True, "sha256": _sha(body)}


def _create(conn: sqlite3.Connection, workspace: Path) -> None:
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


def _open(conn, preimage: dict, postimage: dict) -> str:
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


def test_images_store_sha256_not_source_text(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    body = b"source-not-for-sqlite"
    (ws / "a.py").write_bytes(body)
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    window_id = _open(
        conn,
        preimage={"a.py": _mark(exists=True, body=b"old")},
        postimage={"a.py": _mark(exists=True, body=body)},
    )
    payload = conn.execute(
        "SELECT preimage_json, postimage_json FROM execution_windows WHERE window_id = ?",
        (window_id,),
    ).fetchone()
    blob = (payload[0] or "") + (payload[1] or "")
    assert "source-not-for-sqlite" not in blob
    stored = json.loads(payload[1])
    assert stored["a.py"]["exists"] is True
    assert stored["a.py"]["sha256"] == _sha(body)
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "running"


def test_create_file_postimage(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    body = b"new-file"
    (ws / "created.txt").write_bytes(body)
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _open(
        conn,
        preimage={"created.txt": _mark(exists=False)},
        postimage={"created.txt": _mark(exists=True, body=body)},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "running"


def test_modify_file_postimage(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.txt").write_bytes(b"after")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _open(
        conn,
        preimage={"m.txt": _mark(exists=True, body=b"before")},
        postimage={"m.txt": _mark(exists=True, body=b"after")},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "running"


def test_delete_file_postimage(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _open(
        conn,
        preimage={"gone.txt": _mark(exists=True, body=b"old")},
        postimage={"gone.txt": _mark(exists=False)},
    )
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert _task(conn)["run_state"] == "running"
    assert not (ws / "gone.txt").exists()
