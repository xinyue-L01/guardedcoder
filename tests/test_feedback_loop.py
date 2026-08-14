from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint
from guardedcoder.llm.mock import MockLLM, MockLLMExhaustedError
from guardedcoder.loop.context import build_context
from guardedcoder.loop.engine import step
from guardedcoder.models.actions import ApplyPatchAction, FinishAction
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.models.task import TaskBudget
from guardedcoder.models.verdict import Verdict, VerdictStatus
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task

_FAKE_KEY = "sk" + "-test"


class _CaptureLLM(MockLLM):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.seen: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages)
        return super().complete(messages)


def _diff(old: str, new: str) -> str:
    return (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,1 +1,1 @@\n"
        f"-{old.rstrip()}\n"
        f"+{new.rstrip()}\n"
    )


def _patch_json(old: str, new: str) -> str:
    return json.dumps({"action": "apply_patch", "diff": _diff(old, new)})


def _fail_verdict_text() -> str:
    return Verdict(
        profile_id="pytest",
        sensor="exit_code",
        status=VerdictStatus.FAIL,
        exit_code=1,
        summary="command exited with code 1",
        output_truncated=False,
        output_sha256="0" * 64,
        duration_seconds=0.05,
    ).model_dump_json()


def _pass_verdict_text() -> str:
    return Verdict(
        profile_id="pytest",
        sensor="exit_code",
        status=VerdictStatus.PASS,
        exit_code=0,
        summary="command exited successfully",
        output_truncated=False,
        output_sha256="0" * 64,
        duration_seconds=0.05,
    ).model_dump_json()


def _envelope() -> Envelope:
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


def _fp(conn: sqlite3.Connection, envelope: Envelope, action: object) -> str:
    task = _task(conn)
    return compute_fingerprint(
        schema_version=SCHEMA_VERSION,
        task_id=task["task_id"],
        envelope_hash=envelope.envelope_hash,
        base_commit=task["base_commit"],
        worktree_identity=task["worktree_identity"],
        normalized_action=action.model_dump(mode="json"),
    )


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_bytes(b"before\n")
    return ws


def test_gated_complete_without_fail_verdict_does_not_emit_correction_patch() -> None:
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = MockLLM(responses=[patch1, patch2], gate_on_fail=True)

    first = llm.complete([{"role": "user", "content": "start"}])
    assert first == patch1

    second = llm.complete([{"role": "user", "content": "still no verdict"}])
    assert patch2 not in second
    assert '"apply_patch"' not in second
    payload = json.loads(second)
    assert payload["action"] == "finish"
    assert payload["outcome"] in {"blocked", "failed"}


def test_isolated_fail_word_does_not_unlock_correction() -> None:
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = MockLLM(responses=[patch1, patch2], gate_on_fail=True)
    llm.complete([{"role": "user", "content": "start"}])

    second = llm.complete(
        [{"role": "user", "content": "task must FAIL if tests FAIL"}]
    )
    assert patch2 not in second
    assert '"apply_patch"' not in second


def test_pass_verdict_does_not_unlock_correction() -> None:
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = MockLLM(responses=[patch1, patch2], gate_on_fail=True)
    llm.complete([{"role": "user", "content": "start"}])

    second = llm.complete([{"role": "user", "content": _pass_verdict_text()}])
    assert patch2 not in second
    assert '"apply_patch"' not in second


def test_fail_verdict_structured_text_unlocks_correction() -> None:
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = MockLLM(responses=[patch1, patch2], gate_on_fail=True)
    llm.complete([{"role": "user", "content": "start"}])

    second = llm.complete([{"role": "user", "content": _fail_verdict_text()}])
    assert second == patch2


def test_default_gate_off_still_pops_unconditionally() -> None:
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = MockLLM(responses=[patch1, patch2])
    assert llm.complete([{"role": "user", "content": "a"}]) == patch1
    assert llm.complete([{"role": "user", "content": "b"}]) == patch2
    with pytest.raises(MockLLMExhaustedError):
        llm.complete([{"role": "user", "content": "c"}])


def test_step_without_fail_verdict_does_not_emit_correction_patch(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = _CaptureLLM(responses=[patch1, patch2], gate_on_fail=True)
    fake = _FAKE_KEY

    first = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description=f"first patch {fake}",
    )
    assert isinstance(first.action, ApplyPatchAction)
    assert (ws / "a.txt").read_bytes() == b"after\n"
    first_fp = _fp(conn, envelope, first.action)

    second = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description=f"first patch {fake}",
        observations=[Observation(body="tests still running", truncated=False)],
    )
    assert not isinstance(second.action, ApplyPatchAction)
    assert isinstance(second.action, FinishAction)
    assert second.action.outcome in {"blocked", "failed"}
    assert (ws / "a.txt").read_bytes() == b"after\n"
    assert _fp(conn, envelope, second.action) != first_fp
    blob = json.dumps(llm.seen[-1])
    assert '"status": "FAIL"' not in blob
    assert '"status":"FAIL"' not in blob
    assert fake not in blob


def test_step_with_fail_verdict_changes_next_fingerprint(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    envelope = _envelope()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)
    patch1 = _patch_json("before", "after")
    patch2 = _patch_json("after", "fixed")
    llm = _CaptureLLM(responses=[patch1, patch2], gate_on_fail=True)
    fake = _FAKE_KEY
    fail_text = _fail_verdict_text()

    first = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description=f"fix after sensor FAIL {fake}",
    )
    assert isinstance(first.action, ApplyPatchAction)
    first_fp = _fp(conn, envelope, first.action)

    messages = build_context(
        task_description=f"fix after sensor FAIL {fake}",
        envelope=envelope,
        budget=TaskBudget(remaining_steps=_task(conn)["remaining_steps"]),
        observations=[Observation(body=fail_text, truncated=False)],
    )
    assert fail_text in messages[-1]["content"]
    assert "status" in messages[-1]["content"]
    assert "sensor" in messages[-1]["content"]
    assert "profile_id" in messages[-1]["content"]
    assert fake not in json.dumps(messages)

    second = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=llm,
        worktree=ws,
        task_description=f"fix after sensor FAIL {fake}",
        observations=[Observation(body=fail_text, truncated=False)],
    )
    assert isinstance(second.action, ApplyPatchAction)
    assert second.action.diff != first.action.diff
    second_fp = _fp(conn, envelope, second.action)
    assert second_fp != first_fp
    assert (ws / "a.txt").read_bytes() == b"fixed\n"

    seen_blob = json.dumps(llm.seen[-1])
    assert "FAIL" in seen_blob
    assert "sensor" in seen_blob
    assert "profile_id" in seen_blob
    assert fail_text in llm.seen[-1][-1]["content"]
    assert fake not in seen_blob
