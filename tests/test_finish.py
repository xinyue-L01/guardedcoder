from __future__ import annotations

import hashlib
import inspect
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from guardedcoder.llm.mock import MockLLM
from guardedcoder.loop import engine as engine_mod
from guardedcoder.loop.engine import step
from guardedcoder.models.actions import FinishAction, RunCommandAction
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task
from guardedcoder.workspace.artifact import PatchArtifact


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class InjectedPort:
    over_limit: bool = False
    exports: list[object] = field(default_factory=list)

    def export(self, task: object) -> PatchArtifact:
        self.exports.append(task)
        body = b"diff --git a/f b/f\n"
        return PatchArtifact(
            body=body,
            sha256=_sha(body),
            path=Path("stub.patch"),
            over_limit=self.over_limit,
        )


def _profile(
    profile_id: str, exit_code: int, *, sensor: str | None = "exit_code"
) -> CommandProfile:
    return CommandProfile(
        profile_id=profile_id,
        argv_template=(
            sys.executable,
            "-c",
            f"raise SystemExit({exit_code})",
        ),
        cwd=".",
        timeout_seconds=30,
        max_output_bytes=4096,
        sensor=sensor,
    )


def _envelope(*profiles: CommandProfile, verify: tuple[str, ...] | None = None) -> Envelope:
    if verify is None:
        verify = tuple(item.profile_id for item in profiles)
    return Envelope(
        read_paths=(".",),
        write_paths=(".",),
        profiles=profiles,
        verify_profiles=verify,
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def _boot(
    conn: sqlite3.Connection,
    workspace: Path,
    envelope: Envelope,
    *,
    remaining_steps: int = 10,
) -> None:
    create_task(
        conn,
        task_id="t1",
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash=envelope.envelope_hash,
        remaining_steps=remaining_steps,
    )


def _task(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("t1",)).fetchone()
    assert row is not None
    return row


def _spy_order(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection) -> SimpleNamespace:
    order: list[str] = []
    consumed_at_execute: list[int] = []
    run_state_at_consume: list[str] = []
    run_state_at_execute: list[str] = []

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
        run_state_at_consume.append(str(_task(conn)["run_state"]))
        return real_consume(*args, **kwargs)

    def spy_execute(*args: object, **kwargs: object):
        order.append("executor.execute")
        run_state_at_execute.append(str(_task(conn)["run_state"]))
        permit_id = kwargs["permit_id"]
        row = conn.execute(
            "SELECT consumed FROM permits WHERE permit_id = ?",
            (permit_id,),
        ).fetchone()
        assert row is not None
        consumed_at_execute.append(int(row[0]))
        action = kwargs["action"]
        assert isinstance(action, RunCommandAction)
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "evaluate", spy_evaluate)
    monkeypatch.setattr(engine_mod, "create_permit", spy_create)
    monkeypatch.setattr(engine_mod, "consume_permit_and_open_window", spy_consume)
    monkeypatch.setattr(engine_mod, "execute", spy_execute)
    return SimpleNamespace(
        calls=order,
        consumed_at_execute=consumed_at_execute,
        run_state_at_consume=run_state_at_consume,
        run_state_at_execute=run_state_at_execute,
    )


def _run_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    envelope: Envelope,
    outcome: str,
    remaining_steps: int = 10,
    over_limit: bool = False,
) -> tuple[object, sqlite3.Connection, InjectedPort, SimpleNamespace]:
    ws = tmp_path / "ws"
    ws.mkdir()
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope, remaining_steps=remaining_steps)
    port = InjectedPort(over_limit=over_limit)
    spy = _spy_order(monkeypatch, conn)
    fake = "sk" + "-test"
    result = step(
        conn,
        task_id="t1",
        envelope=envelope,
        llm=MockLLM(responses=[f'{{"action":"finish","outcome":"{outcome}"}}']),
        worktree=ws,
        task_description=f"done {fake}",
        task_dir=tmp_path / "task",
        patch_port=port,
    )
    return result, conn, port, spy


def test_finish_success_without_verify_is_unverified_no_execute_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(verify=())
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert isinstance(result.action, FinishAction)
    assert result.run_state == "unverified"
    assert _task(conn)["run_state"] == "unverified"
    assert result.observation is None
    assert "create_permit" not in spy.calls
    assert "executor.execute" not in spy.calls
    assert port.exports == []
    assert "GitPatchArtifactPort" not in Path(engine_mod.__file__).read_text(
        encoding="utf-8"
    )


def test_finish_success_verify_all_pass_and_stub_not_over_limit_is_succeeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert result.run_state == "succeeded"
    assert _task(conn)["run_state"] == "succeeded"
    assert _task(conn)["artifact_state"] == "patch_ready"
    assert len(port.exports) == 1
    assert "executor.execute" in spy.calls


def test_sensor_non_pass_cannot_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 1))
    result, conn, port, _spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert "executor.execute" in _spy.calls
    assert result.run_state != "succeeded"
    assert _task(conn)["run_state"] != "succeeded"
    assert _task(conn)["run_state"] in {"running", "exhausted"}
    assert _task(conn)["artifact_state"] != "patch_ready"
    assert port.exports == []


def test_sensors_pass_but_stub_over_limit_cannot_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0))
    result, conn, port, _spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success", over_limit=True
    )

    assert "executor.execute" in _spy.calls
    assert result.run_state != "succeeded"
    assert _task(conn)["run_state"] != "succeeded"
    assert _task(conn)["artifact_state"] != "patch_ready"
    assert len(port.exports) == 1


def test_verify_db_run_state_is_verifying_not_executing_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0))
    _result, _conn, _port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert spy.run_state_at_consume
    assert spy.run_state_at_execute
    assert spy.run_state_at_consume == ["verifying"] * len(spy.run_state_at_consume)
    assert spy.run_state_at_execute == ["verifying"] * len(spy.run_state_at_execute)
    assert "executing_action" not in spy.run_state_at_consume
    assert "executing_action" not in spy.run_state_at_execute


def test_verify_run_command_uses_t28_permit_order_and_consumed_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0), _profile("lint", 0))
    _result, conn, _port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert spy.calls == [
        "evaluate",
        "evaluate",
        "create_permit",
        "consume_permit_and_open_window",
        "executor.execute",
        "evaluate",
        "create_permit",
        "consume_permit_and_open_window",
        "executor.execute",
    ]
    assert spy.consumed_at_execute == [1, 1]
    permits = conn.execute("SELECT consumed FROM permits").fetchall()
    assert [int(row[0]) for row in permits] == [1, 1]


def test_finish_failed_is_terminal_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="failed"
    )

    assert result.run_state == "failed"
    assert _task(conn)["run_state"] == "failed"
    assert result.run_state != "succeeded"
    assert "executor.execute" not in spy.calls
    assert port.exports == []


def test_finish_blocked_is_terminal_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="blocked"
    )

    assert result.run_state == "blocked"
    assert _task(conn)["run_state"] == "blocked"
    assert result.run_state != "succeeded"
    assert "executor.execute" not in spy.calls
    assert port.exports == []


def test_sensor_fail_with_exhausted_budget_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 1))
    result, conn, _port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success", remaining_steps=1
    )

    assert "executor.execute" in spy.calls
    assert result.run_state == "exhausted"
    assert _task(conn)["run_state"] == "exhausted"
    assert result.run_state != "succeeded"


def test_stub_port_returns_fixed_small_patch_or_over_limit() -> None:
    from guardedcoder.loop.ports import StubPatchArtifactPort

    small = StubPatchArtifactPort(over_limit=False).export(object())
    limited = StubPatchArtifactPort(over_limit=True).export(object())

    assert small.over_limit is False
    assert small.can_mark_patch_ready is True
    assert limited.over_limit is True
    assert limited.can_mark_patch_ready is False
    assert "GitPatchArtifactPort" not in inspect.getsource(
        sys.modules["guardedcoder.loop.ports"]
    )


@pytest.mark.parametrize("outcome", ["", "done", "Success", "SUCCESS", "ok"])
def test_unknown_finish_outcome_is_blocked_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    envelope = _envelope(_profile("unit", 0))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome=outcome
    )

    assert result.run_state == "blocked"
    assert _task(conn)["run_state"] == "blocked"
    assert result.run_state != "succeeded"
    assert result.run_state != "unverified"
    assert "executor.execute" not in spy.calls
    assert "create_permit" not in spy.calls
    assert port.exports == []


def test_undeclared_sensor_is_error_and_cannot_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0, sensor=None))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert "executor.execute" in spy.calls
    assert result.run_state != "succeeded"
    assert _task(conn)["run_state"] != "succeeded"
    assert _task(conn)["artifact_state"] != "patch_ready"
    assert port.exports == []


def test_unknown_sensor_is_error_and_cannot_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = _envelope(_profile("unit", 0, sensor="coverage_xml"))
    result, conn, port, spy = _run_finish(
        tmp_path, monkeypatch, envelope=envelope, outcome="success"
    )

    assert "executor.execute" in spy.calls
    assert result.run_state != "succeeded"
    assert _task(conn)["run_state"] != "succeeded"
    assert _task(conn)["artifact_state"] != "patch_ready"
    assert port.exports == []


def test_verify_execute_failure_fail_closes_window_to_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    envelope = _envelope(_profile("unit", 0))
    conn = connect(tmp_path / "g.db")
    _boot(conn, ws, envelope)

    def boom(*args: object, **kwargs: object):
        raise RuntimeError("verify execute exploded")

    monkeypatch.setattr(engine_mod, "execute", boom)
    with pytest.raises(RuntimeError, match="verify execute exploded"):
        step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=MockLLM(responses=['{"action":"finish","outcome":"success"}']),
            worktree=ws,
            task_description="done",
            task_dir=tmp_path / "task",
            patch_port=InjectedPort(),
        )

    assert _task(conn)["run_state"] == "error"
    row = conn.execute("SELECT status FROM execution_windows").fetchone()
    assert row is not None
    assert row[0] == "error"
