from __future__ import annotations

from guardedcoder.persist.audit import append_audit
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task


def test_append_audit_redacts_key_shaped_substrings(tmp_path) -> None:
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
        remaining_steps=3,
    )
    fake = "sk" + "-live" + "AbCdEfGh123"
    event = {
        "note": "prefix " + fake + " suffix",
        "nested": {"token": fake},
        "items": [fake, {"k": fake}],
    }
    append_audit(conn, "t1", event)
    payload = conn.execute("SELECT payload_json FROM audit_events").fetchone()[0]
    assert fake not in payload
    assert ("sk" + "-live") not in payload
    assert "[redacted]" in payload
