from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from guardedcoder.errors import ClaimConflictError, PermitInvalidError, PatchError
from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint
from guardedcoder.governance.evaluate import Verdict, VerdictKind
from guardedcoder.llm.mock import MockLLM
from guardedcoder.loop import engine as engine_mod
from guardedcoder.loop.context import build_context
from guardedcoder.loop.engine import step
from guardedcoder.models.actions import Action, ApplyPatchAction, ListDirAction
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.models.task import TaskBudget
from guardedcoder.persist.claim import claim_recovered_attempt
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.store import create_task


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mark(exists: bool, body: str | None = None) -> dict:
    if not exists:
        return {"exists": False, "sha256": None}
    assert body is not None
    return {"exists": True, "sha256": _sha(body)}


def _envelope() -> Envelope:
    return Envelope(
        read_paths=("src",),
        write_paths=("src",),
        profiles=(
            CommandProfile(
                profile_id="pytest",
                argv_template=["pytest", "--junitxml", "{junit_out}"],
                cwd=".",
                timeout_seconds=60,
                max_output_bytes=65536,
            ),
        ),
        verify_profiles=("pytest",),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def _boot(conn: sqlite3.Connection, workspace: Path, envelope: Envelope) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash=envelope.envelope_hash,
        remaining_steps=10,
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def _diff(old: str, new: str) -> str:
    return (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        f"-{old.rstrip()}\n"
        f"+{new.rstrip()}\n"
    )


def _fp_for(conn: sqlite3.Connection, envelope: Envelope, action: Action) -> str:
    task = _task(conn)
    return compute_fingerprint(
        schema_version=SCHEMA_VERSION,
        task_id=task["task_id"],
        envelope_hash=envelope.envelope_hash,
        base_commit=task["base_commit"],
        worktree_identity=task["worktree_identity"],
        normalized_action=action.model_dump(mode="json"),
    )


def _patch_envelope() -> Envelope:
    return Envelope(
        read_paths=(".",),
        write_paths=(".",),
        profiles=(),
        verify_profiles=(),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def _open_apply_window(
    conn: sqlite3.Connection,
    envelope: Envelope,
    diff: str,
    *,
    pre: str,
    post: str,
    started: bool,
) -> tuple[str, str]:
    action = ApplyPatchAction(action="apply_patch", diff=diff)
    permit_id = create_permit(
        conn,
        task_id="t1",
        action_id="a1",
        fingerprint=_fp_for(conn, envelope, action),
        envelope_hash=envelope.envelope_hash,
        expected_revision=_task(conn)["state_revision"],
    )
    window_id = consume_permit_and_open_window(
        conn,
        task_id="t1",
        permit_id=permit_id,
        expected_revision=_task(conn)["state_revision"],
        action_kind="apply_patch",
        preimage={"a.txt": _mark(True, pre)},
        postimage={"a.txt": _mark(True, post)},
    )
    if started:
        conn.execute(
            "UPDATE execution_windows SET execution_started = 1 WHERE window_id = ?",
            (window_id,),
        )
    return permit_id, window_id


def _spy_order(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection) -> SimpleNamespace:
    order: list[str] = []
    consumed_at_execute: list[int] = []

    real_evaluate = engine_mod.evaluate
    real_create = engine_mod.create_permit
    real_consume = engine_mod.consume_permit_and_open_window
    real_execute = engine_mod.execute

    def spy_evaluate(*args: object, **kwargs: object):
        order.append("evaluate")
        return real_evaluate(*args, **kwargs)

    def spy_create(*args: object, **kwargs: object):
        order.append("create_permit")
        return real_create(*args, **kwargs)

    def spy_consume(*args: object, **kwargs: object):
        order.append("consume_permit_and_open_window")
        return real_consume(*args, **kwargs)

    def spy_execute(*args: object, **kwargs: object):
        order.append("executor.execute")
        permit_id = kwargs["permit_id"]
        row = conn.execute(
            "SELECT consumed FROM permits WHERE permit_id = ?",
            (permit_id,),
        ).fetchone()
        assert row is not None
        consumed_at_execute.append(int(row[0]))
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "evaluate", spy_evaluate)
    monkeypatch.setattr(engine_mod, "create_permit", spy_create)
    monkeypatch.setattr(engine_mod, "consume_permit_and_open_window", spy_consume)
    monkeypatch.setattr(engine_mod, "execute", spy_execute)
    return SimpleNamespace(calls=order, consumed_at_execute=consumed_at_execute)


def test_step_calls_evaluate_create_consume_execute_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    src = ws / "src"
    src.mkdir(parents=True)
    (src / "a.py").write_text("print(1)\n", encoding="utf-8")
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    spy = _spy_order(monkeypatch, conn)
    llm = MockLLM(responses=['{"action":"list_dir","path":"src"}'])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="list sources",
    )

    assert spy.calls == [
        "evaluate",
        "create_permit",
        "consume_permit_and_open_window",
        "executor.execute",
    ]
    assert spy.consumed_at_execute == [1]
    assert isinstance(result.action, ListDirAction)
    assert result.observation is not None
    assert "a.py" in result.observation.body
    permit = conn.execute("SELECT consumed FROM permits").fetchone()
    assert permit is not None
    assert permit[0] == 1


def test_need_approval_requests_hitl_without_permit_or_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    spy = _spy_order(monkeypatch, conn)

    def need_approval(*args: object, **kwargs: object) -> Verdict:
        spy.calls.append("evaluate")
        return Verdict(kind=VerdictKind.NeedApproval, code=None)

    monkeypatch.setattr(engine_mod, "evaluate", need_approval)
    llm = MockLLM(responses=['{"action":"list_dir","path":"src"}'])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="needs hitl",
    )

    assert "create_permit" not in spy.calls
    assert "consume_permit_and_open_window" not in spy.calls
    assert "executor.execute" not in spy.calls
    assert _task(conn)["run_state"] == "awaiting_approval"
    pending = conn.execute("SELECT consumed FROM pending_actions").fetchone()
    assert pending is not None
    assert pending[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
    assert result.observation is None


def test_recovered_apply_patch_claims_then_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    diff = _diff("before", "after")
    _open_apply_window(
        conn, envelope, diff, pre="before\n", post="after\n", started=True
    )
    order: list[str] = []
    real_claim = engine_mod.claim_recovered_attempt
    real_execute = engine_mod.execute
    real_create = engine_mod.create_permit

    def spy_claim(*args: object, **kwargs: object):
        order.append("claim_recovered_attempt")
        return real_claim(*args, **kwargs)

    def spy_execute(*args: object, **kwargs: object):
        order.append("executor.execute")
        assert kwargs.get("claim_id")
        return real_execute(*args, **kwargs)

    def spy_create(*args: object, **kwargs: object):
        order.append("create_permit")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "claim_recovered_attempt", spy_claim)
    monkeypatch.setattr(engine_mod, "execute", spy_execute)
    monkeypatch.setattr(engine_mod, "create_permit", spy_create)
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="retry patch",
    )

    assert "create_permit" not in order
    assert order[:2] == ["claim_recovered_attempt", "executor.execute"]
    assert (ws / "a.txt").read_bytes() == b"after\n"
    assert result.observation is not None


def test_recovered_apply_patch_without_claim_does_not_execute(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    diff = _diff("before", "after")
    _permit_id, window_id = _open_apply_window(
        conn, envelope, diff, pre="before\n", post="after\n", started=True
    )
    claim_recovered_attempt(
        conn,
        task_id="t1",
        window_id=window_id,
        expected_revision=_task(conn)["state_revision"],
        attempt_id="held",
    )
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    with pytest.raises(ClaimConflictError):
        step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=llm,
            worktree=ws,
            task_description="retry patch",
        )

    assert (ws / "a.txt").read_bytes() == b"before\n"


def test_finish_is_noop_without_permit_or_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    spy = _spy_order(monkeypatch, conn)
    llm = MockLLM(responses=['{"action":"finish","outcome":"success"}'])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="done",
    )

    assert "create_permit" not in spy.calls
    assert "executor.execute" not in spy.calls
    assert _task(conn)["run_state"] == "running"
    assert result.observation is None


def test_deny_does_not_create_permit_or_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    spy = _spy_order(monkeypatch, conn)
    llm = MockLLM(responses=['{"action":"read_file","path":"../secret"}'])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="escape",
    )

    assert spy.calls == ["evaluate"]
    assert "create_permit" not in spy.calls
    assert "executor.execute" not in spy.calls
    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
    assert result.observation is None


def test_fresh_apply_patch_uses_permit_then_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = Envelope(
        read_paths=(".",),
        write_paths=(".",),
        profiles=(),
        verify_profiles=(),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    spy = _spy_order(monkeypatch, conn)
    diff = _diff("before", "after")
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="patch file",
    )

    assert spy.calls == [
        "evaluate",
        "create_permit",
        "consume_permit_and_open_window",
        "executor.execute",
    ]
    assert spy.consumed_at_execute == [1]
    assert isinstance(result.action, ApplyPatchAction)
    assert (ws / "a.txt").read_bytes() == b"after\n"


def test_build_context_redacts_concatenated_fake_key() -> None:
    fake = "sk" + "-test"
    messages = build_context(
        task_description=f"token {fake} must not leak",
        envelope=_envelope(),
        budget=TaskBudget(remaining_steps=4),
    )
    blob = json.dumps(messages)
    assert fake not in blob
    assert any(item["role"] == "user" for item in messages)
    assert "4" in blob


def test_fingerprint_matches_normalized_action_for_hitl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)

    def need_approval(*args: object, **kwargs: object) -> Verdict:
        return Verdict(kind=VerdictKind.NeedApproval, code=None)

    monkeypatch.setattr(engine_mod, "evaluate", need_approval)
    llm = MockLLM(responses=['{"action":"list_dir","path":"src"}'])
    step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="hitl fp",
    )
    row = conn.execute(
        "SELECT fingerprint, normalized_action_json FROM pending_actions"
    ).fetchone()
    assert row is not None
    normalized = json.loads(row[1])
    task = _task(conn)
    expected = compute_fingerprint(
        schema_version=SCHEMA_VERSION,
        task_id="t1",
        envelope_hash=envelope.envelope_hash,
        base_commit=task["base_commit"],
        worktree_identity=task["worktree_identity"],
        normalized_action=normalized,
    )
    assert row[0] == expected


def test_preview_failure_does_not_leave_unconsumed_permit(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    llm = MockLLM(
        responses=[json.dumps({"action": "apply_patch", "diff": "not-a-diff"})]
    )

    with pytest.raises(PatchError):
        step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=llm,
            worktree=ws,
            task_description="bad patch",
        )

    assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
    assert _task(conn)["remaining_steps"] == 10
    assert _task(conn)["run_state"] == "running"


def test_execute_failure_closes_window_so_next_step_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    real_execute = engine_mod.execute
    calls = {"n": 0}

    def boom_once(*args: object, **kwargs: object):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("execute exploded")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "execute", boom_once)
    with pytest.raises(RuntimeError, match="execute exploded"):
        step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=MockLLM(responses=['{"action":"list_dir","path":"src"}']),
            worktree=ws,
            task_description="first",
        )
    row = conn.execute(
        "SELECT status, execution_started FROM execution_windows"
    ).fetchone()
    assert row is not None
    assert row[0] in {"error", "failed"}
    assert _task(conn)["run_state"] != "executing_action"

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=MockLLM(responses=['{"action":"list_dir","path":"src"}']),
        worktree=ws,
        task_description="second",
    )
    assert result.observation is not None
    assert "a.py" in result.observation.body


def test_consume_sees_workspace_still_at_preimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    at_consume: list[bytes] = []
    real_consume = engine_mod.consume_permit_and_open_window

    def spy_consume(*args: object, **kwargs: object):
        at_consume.append((ws / "a.txt").read_bytes())
        return real_consume(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "consume_permit_and_open_window", spy_consume)
    diff = _diff("before", "after")
    step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})]),
        worktree=ws,
        task_description="patch file",
    )
    assert at_consume == [b"before\n"]
    assert (ws / "a.txt").read_bytes() == b"after\n"


def test_recovered_fingerprint_mismatch_does_not_execute(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    original = _diff("before", "after")
    _open_apply_window(
        conn, envelope, original, pre="before\n", post="after\n", started=True
    )
    other = _diff("before", "other")
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": other})])

    with pytest.raises(PermitInvalidError):
        step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=llm,
            worktree=ws,
            task_description="wrong patch",
        )

    assert (ws / "a.txt").read_bytes() == b"before\n"
    win = conn.execute(
        "SELECT status FROM execution_windows WHERE status = 'executing_action'"
    ).fetchone()
    assert win is not None


def test_recorded_success_returns_observation_without_claim_or_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"after\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    diff = _diff("before", "after")
    _open_apply_window(
        conn, envelope, diff, pre="before\n", post="after\n", started=True
    )
    claimed: list[object] = []
    executed: list[object] = []

    def spy_claim(*args: object, **kwargs: object) -> str:
        claimed.append(kwargs)
        raise AssertionError("claim must not run on recorded_success")

    def spy_execute(*args: object, **kwargs: object):
        executed.append(kwargs)
        raise AssertionError("execute must not run on recorded_success")

    monkeypatch.setattr(engine_mod, "claim_recovered_attempt", spy_claim)
    monkeypatch.setattr(engine_mod, "execute", spy_execute)
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="already done",
    )

    assert claimed == []
    assert executed == []
    assert result.observation is not None
    assert _task(conn)["run_state"] == "running"
    assert (ws / "a.txt").read_bytes() == b"after\n"
    status = conn.execute("SELECT status FROM execution_windows").fetchone()
    assert status is not None
    assert status[0] == "succeeded"


def test_recorded_error_does_not_raise_window_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"other\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    diff = _diff("before", "after")
    _open_apply_window(
        conn, envelope, diff, pre="before\n", post="after\n", started=True
    )
    executed: list[object] = []

    def spy_execute(*args: object, **kwargs: object):
        executed.append(kwargs)
        raise AssertionError("execute must not run on recorded_error")

    monkeypatch.setattr(engine_mod, "execute", spy_execute)
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="corrupt workspace",
    )

    assert executed == []
    assert result.run_state == "error"
    assert _task(conn)["run_state"] == "error"
    assert (ws / "a.txt").read_bytes() == b"other\n"


def test_unstarted_window_resumes_first_apply_without_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    envelope = _patch_envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    diff = _diff("before", "after")
    _open_apply_window(
        conn, envelope, diff, pre="before\n", post="after\n", started=False
    )
    claimed: list[object] = []
    created: list[object] = []

    def spy_claim(*args: object, **kwargs: object) -> str:
        claimed.append(kwargs)
        raise AssertionError("first apply must not claim")

    def spy_create(*args: object, **kwargs: object) -> str:
        created.append(kwargs)
        raise AssertionError("must reuse consumed permit")

    monkeypatch.setattr(engine_mod, "claim_recovered_attempt", spy_claim)
    monkeypatch.setattr(engine_mod, "create_permit", spy_create)
    llm = MockLLM(responses=[json.dumps({"action": "apply_patch", "diff": diff})])

    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description="resume first apply",
    )

    assert claimed == []
    assert created == []
    assert (ws / "a.txt").read_bytes() == b"after\n"
    assert result.observation is not None


def test_engine_uses_public_preview_not_privates() -> None:
    source = Path(engine_mod.__file__).read_text(encoding="utf-8")
    assert "preview_patch" in source
    for name in (
        "_parse_diff",
        "_apply_hunks",
        "_involved_paths",
        "_read_text",
        "_mark_bytes",
    ):
        assert name not in source
