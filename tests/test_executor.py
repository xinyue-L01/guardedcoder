from __future__ import annotations

import hashlib
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

from guardedcoder.errors import PatchError, UnauthorizedError
from guardedcoder.models.actions import ApplyPatchAction, ListDirAction, RunCommandAction
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.persist.claim import ClaimConflictError, claim_recovered_attempt
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.persist.store import create_task
from guardedcoder.tools import executor
from guardedcoder.tools.executor import execute


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mark(exists: bool, body: str | None = None) -> dict:
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
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash="env-1",
        remaining_steps=10,
    )


def _open_patch(
    conn: sqlite3.Connection,
    workspace: Path,
    *,
    before: str = "before\n",
    after: str = "after\n",
) -> tuple[str, str]:
    (workspace / "a.txt").write_bytes(before.encode("utf-8"))
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
        preimage={"a.txt": _mark(True, before)},
        postimage={"a.txt": _mark(True, after)},
    )
    return permit_id, window_id


def _diff(old: str, new: str) -> str:
    return (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        f"-{old.rstrip()}\n"
        f"+{new.rstrip()}\n"
    )


def _mark_started(conn: sqlite3.Connection, window_id: str) -> None:
    conn.execute(
        "UPDATE execution_windows SET execution_started = 1 WHERE window_id = ?",
        (window_id,),
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def test_executor_source_never_mints_permits_or_claims() -> None:
    source = inspect.getsource(executor)
    assert "create_permit" not in source
    assert "consume_permit_and_open_window" not in source
    assert "claim_recovered_attempt" not in source


def test_1_two_connections_one_claim_wins(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    db = tmp_path / "g.db"
    conn1 = connect(db)
    _create(conn1, ws)
    _permit, window_id = _open_patch(conn1, ws)
    _mark_started(conn1, window_id)
    conn2 = connect(db)
    won = 0
    for conn in (conn1, conn2):
        try:
            claim_recovered_attempt(
                conn,
                task_id="t1",
                window_id=window_id,
                expected_revision=3,
                attempt_id="1",
            )
            won += 1
        except ClaimConflictError:
            pass
    assert won == 1


def test_2_two_recover_results_cannot_double_execute(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    db = tmp_path / "g.db"
    conn1 = connect(db)
    _create(conn1, ws)
    permit_id, window_id = _open_patch(conn1, ws)
    _mark_started(conn1, window_id)
    conn2 = connect(db)
    first = recover(conn1, task_id="t1", workspace=ws, expected_revision=3)
    second = recover(conn2, task_id="t1", workspace=ws, expected_revision=3)
    assert first == RecoverDecision.retryable_same_attempt
    assert second == RecoverDecision.retryable_same_attempt
    claim_id = claim_recovered_attempt(
        conn1,
        task_id="t1",
        window_id=window_id,
        expected_revision=3,
        attempt_id="1",
    )
    action = ApplyPatchAction(action="apply_patch", diff=_diff("before", "after"))
    execute(
        conn1,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=action,
        worktree=ws,
        claim_id=claim_id,
    )
    with pytest.raises(UnauthorizedError):
        execute(
            conn2,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=ws,
            claim_id=claim_id,
        )
    assert (ws / "a.txt").read_bytes() == b"after\n"


def test_3_m5_without_claim_leaves_files_unchanged(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    _mark_started(conn, window_id)
    recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ApplyPatchAction(action="apply_patch", diff=_diff("before", "after")),
            worktree=ws,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_4_stale_or_wrong_claim_is_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    _mark_started(conn, window_id)
    claim_id = claim_recovered_attempt(
        conn,
        task_id="t1",
        window_id=window_id,
        expected_revision=3,
        attempt_id="1",
    )
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ApplyPatchAction(action="apply_patch", diff=_diff("before", "after")),
            worktree=ws,
            claim_id="not-the-claim",
        )
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id="other-window",
            action=ApplyPatchAction(action="apply_patch", diff=_diff("before", "after")),
            worktree=ws,
            claim_id=claim_id,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_5_claim_is_one_shot(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    _mark_started(conn, window_id)
    claim_id = claim_recovered_attempt(
        conn,
        task_id="t1",
        window_id=window_id,
        expected_revision=3,
        attempt_id="1",
    )
    action = ApplyPatchAction(action="apply_patch", diff=_diff("before", "after"))
    execute(
        conn,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=action,
        worktree=ws,
        claim_id=claim_id,
    )
    (ws / "a.txt").write_bytes(b"before\n")
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=ws,
            claim_id=claim_id,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_6_mixed_pre_post_is_error_and_does_not_apply(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    (ws / "a.txt").write_bytes(b"before\n")
    (ws / "b.txt").write_bytes(b"after-b\n")
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
        preimage={"a.txt": _mark(True, "before\n"), "b.txt": _mark(True, "before-b\n")},
        postimage={"a.txt": _mark(True, "after\n"), "b.txt": _mark(True, "after-b\n")},
    )
    decision = recover(conn, task_id="t1", workspace=ws, expected_revision=3)
    assert decision == RecoverDecision.recorded_error
    assert _task(conn)["run_state"] == "error"
    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_7_run_command_recover_does_not_autorun(tmp_path: Path) -> None:
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
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=RunCommandAction(action="run_command", profile_id="pytest"),
            worktree=ws,
            task_dir=tmp_path,
        )


def test_8_normal_permit_path_needs_no_claim(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    execute(
        conn,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=ApplyPatchAction(action="apply_patch", diff=_diff("before", "after")),
        worktree=ws,
    )
    assert (ws / "a.txt").read_bytes() == b"after\n"


def test_bare_action_and_unconsumed_permit_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id="missing",
            window_id="missing",
            action=ListDirAction(action="list_dir", path="."),
            worktree=ws,
        )
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash="env-1",
        expected_revision=1,
    )
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id="missing",
            action=ListDirAction(action="list_dir", path="."),
            worktree=ws,
        )


def test_different_attempt_ids_still_one_claim_wins(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    db = tmp_path / "g.db"
    conn1 = connect(db)
    _create(conn1, ws)
    _permit, window_id = _open_patch(conn1, ws)
    _mark_started(conn1, window_id)
    conn2 = connect(db)
    won = 0
    for conn, attempt_id in ((conn1, "1"), (conn2, "2")):
        try:
            claim_recovered_attempt(
                conn,
                task_id="t1",
                window_id=window_id,
                expected_revision=3,
                attempt_id=attempt_id,
            )
            won += 1
        except ClaimConflictError:
            pass
    assert won == 1


def test_failed_apply_does_not_consume_claim(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    _mark_started(conn, window_id)
    claim_id = claim_recovered_attempt(
        conn,
        task_id="t1",
        window_id=window_id,
        expected_revision=3,
        attempt_id="1",
    )
    with pytest.raises(PatchError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ApplyPatchAction(action="apply_patch", diff=_diff("nope", "after")),
            worktree=ws,
            claim_id=claim_id,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"
    execute(
        conn,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=ApplyPatchAction(action="apply_patch", diff=_diff("before", "after")),
        worktree=ws,
        claim_id=claim_id,
    )
    assert (ws / "a.txt").read_bytes() == b"after\n"


def test_read_tool_rejected_on_apply_patch_window(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ListDirAction(action="list_dir", path="."),
            worktree=ws,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_run_command_second_execute_is_rejected(tmp_path: Path) -> None:
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
    envelope = Envelope(
        read_paths=("src",),
        write_paths=("src",),
        profiles=(
            CommandProfile(
                profile_id="test",
                argv_template=(sys.executable, "-c", "print(0)"),
                cwd=".",
                timeout_seconds=10,
                max_output_bytes=4096,
            ),
        ),
        verify_profiles=("test",),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )
    action = RunCommandAction(action="run_command", profile_id="test")
    execute(
        conn,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=action,
        worktree=ws,
        task_dir=tmp_path,
        envelope=envelope,
    )
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=ws,
            task_dir=tmp_path,
            envelope=envelope,
        )


def test_claim_requires_execution_started(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    _permit, window_id = _open_patch(conn, ws)
    with pytest.raises(UnauthorizedError):
        claim_recovered_attempt(
            conn,
            task_id="t1",
            window_id=window_id,
            expected_revision=3,
            attempt_id="1",
        )


def test_execute_rejects_diff_outside_image(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b.txt").write_bytes(b"keep\n")
    conn = connect(tmp_path / "g.db")
    _create(conn, ws)
    permit_id, window_id = _open_patch(conn, ws)
    diff = (
        "diff --git a/a.txt b/a.txt\n"
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-before\n"
        "+after\n"
        "diff --git a/b.txt b/b.txt\n"
        "--- a/b.txt\n"
        "+++ b/b.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-keep\n"
        "+hacked\n"
    )
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ApplyPatchAction(action="apply_patch", diff=diff),
            worktree=ws,
        )
    assert (ws / "a.txt").read_bytes() == b"before\n"
    assert (ws / "b.txt").read_bytes() == b"keep\n"


def test_execute_passes_allow_delete(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
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
        action_kind="apply_patch",
        preimage={"a.txt": _mark(True, "before\n")},
        postimage={"a.txt": _mark(False)},
    )
    envelope = Envelope(
        read_paths=("src",),
        write_paths=("src",),
        profiles=(),
        verify_profiles=(),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=True,
        allow_network=False,
        config_digest="abc",
    )
    diff = "--- a/a.txt\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-before\n"
    execute(
        conn,
        task_id="t1",
        permit_id=permit_id,
        window_id=window_id,
        action=ApplyPatchAction(action="apply_patch", diff=diff),
        worktree=ws,
        envelope=envelope,
    )
    assert not (ws / "a.txt").exists()


def test_symlink_is_not_treated_as_deleted(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
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
        action_kind="apply_patch",
        preimage={"a.txt": _mark(True, "before\n")},
        postimage={"a.txt": _mark(False)},
    )
    (ws / "a.txt").unlink()
    target = tmp_path / "outside.txt"
    target.write_bytes(b"secret\n")
    try:
        (ws / "a.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation requires privilege on this Windows host")
    with pytest.raises(UnauthorizedError):
        execute(
            conn,
            task_id="t1",
            permit_id=permit_id,
            window_id=window_id,
            action=ApplyPatchAction(
                action="apply_patch",
                diff="--- a/a.txt\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-before\n",
            ),
            worktree=ws,
        )
    assert (ws / "a.txt").is_symlink()
    assert target.read_bytes() == b"secret\n"
