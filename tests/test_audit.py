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


def test_append_audit_redacts_bearer_and_opaque_provider_key(tmp_path) -> None:
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="t2",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(tmp_path),
        base_commit="abc",
        worktree_identity=str(tmp_path.resolve()),
        envelope_hash="env-1",
        remaining_steps=3,
    )
    opaque = "provider-opaque-value-123"
    bearer = "opaque.jwt.token"

    append_audit(
        conn,
        "t2",
        {"message": f"api_key={opaque}; Authorization: Bearer {bearer}"},
    )
    payload = conn.execute(
        "SELECT payload_json FROM audit_events WHERE task_id = 't2'"
    ).fetchone()[0]

    assert opaque not in payload
    assert bearer not in payload
    assert payload.count("[redacted]") == 2
