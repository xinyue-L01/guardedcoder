from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from guardedcoder.errors import (
    ExecutionWindowOpenError,
    PermitInvalidError,
    StaleRevisionError,
)
from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint
from guardedcoder.governance.evaluate import VerdictKind, evaluate
from guardedcoder.llm.port import LLMPort
from guardedcoder.loop.context import build_context
from guardedcoder.loop.ports import PatchArtifactPort, StubPatchArtifactPort
from guardedcoder.models.actions import (
    Action,
    ApplyPatchAction,
    FinishAction,
    ListDirAction,
    ReadFileAction,
    RunCommandAction,
    SearchTextAction,
    parse_llm_response,
)
from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.models.task import TaskBudget
from guardedcoder.models.verdict import Verdict, VerdictStatus
from guardedcoder.persist.approval import request_approval
from guardedcoder.persist.claim import claim_recovered_attempt
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.persist.store import update_task
from guardedcoder.persist.txn import write_txn
from guardedcoder.sensors.common import bounded_summary, output_digest
from guardedcoder.sensors.exit_code import exit_code_verdict
from guardedcoder.sensors.junit_xml import junit_xml_verdict
from guardedcoder.sensors.plan import build_verify_plan
from guardedcoder.tools.apply_patch import preview_patch
from guardedcoder.tools.executor import execute

_ACTION_KIND = {
    ListDirAction: "list_dir",
    ReadFileAction: "read_file",
    SearchTextAction: "search_text",
    ApplyPatchAction: "apply_patch",
    RunCommandAction: "run_command",
}


@dataclass(frozen=True, slots=True)
class StepResult:
    action: Action
    observation: Observation | CommandResult | None
    run_state: str


def _task_row(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT task_id, run_state, base_commit, worktree_identity, "
        "envelope_hash, state_revision, remaining_steps FROM tasks "
        "WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"task {task_id} not found")
    return {
        "task_id": row[0],
        "run_state": row[1],
        "base_commit": row[2],
        "worktree_identity": row[3],
        "envelope_hash": row[4],
        "state_revision": int(row[5]),
        "remaining_steps": int(row[6]),
    }


def _active_window(
    conn: sqlite3.Connection, task_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT window_id, permit_id, action_kind, execution_started "
        "FROM execution_windows WHERE task_id = ? AND status = ? "
        "ORDER BY rowid DESC",
        (task_id, "executing_action"),
    ).fetchone()
    if row is None:
        return None
    return {
        "window_id": row[0],
        "permit_id": row[1],
        "action_kind": row[2],
        "execution_started": bool(row[3]),
    }


def _fingerprint(task: dict[str, Any], envelope: Envelope, action: Action) -> str:
    normalized = action.model_dump(mode="json")
    return compute_fingerprint(
        schema_version=SCHEMA_VERSION,
        task_id=task["task_id"],
        envelope_hash=envelope.envelope_hash,
        base_commit=task["base_commit"],
        worktree_identity=task["worktree_identity"],
        normalized_action=normalized,
    )


def _permit_fingerprint(conn: sqlite3.Connection, permit_id: str) -> str:
    row = conn.execute(
        "SELECT fingerprint FROM permits WHERE permit_id = ?",
        (permit_id,),
    ).fetchone()
    if row is None:
        raise PermitInvalidError(f"permit {permit_id} not found")
    return str(row[0])


def _require_matching_fingerprint(
    conn: sqlite3.Connection,
    *,
    task: dict[str, Any],
    envelope: Envelope,
    action: Action,
    permit_id: str,
) -> None:
    expected = _fingerprint(task, envelope, action)
    stored = _permit_fingerprint(conn, permit_id)
    if expected != stored:
        raise PermitInvalidError(f"fingerprint mismatch for permit {permit_id}")


def _complete_window(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    window_id: str,
    run_state: str = "running",
) -> None:
    task = _task_row(conn, task_id)
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ?",
            (run_state, task_id, task["state_revision"]),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {task['state_revision']}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            ("succeeded", window_id),
        )


def _fail_close_window(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    window_id: str,
    run_state: str = "running",
) -> None:
    task = _task_row(conn, task_id)
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ?",
            (run_state, task_id, task["state_revision"]),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {task['state_revision']}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            ("error", window_id),
        )


def _hitl(
    conn: sqlite3.Connection,
    *,
    task: dict[str, Any],
    envelope: Envelope,
    action: Action,
) -> None:
    normalized = action.model_dump(mode="json")
    request_approval(
        conn,
        task_id=task["task_id"],
        fingerprint=_fingerprint(task, envelope, action),
        normalized_action_json=json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ),
        expected_revision=task["state_revision"],
    )


def _retry_started_patch(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    envelope: Envelope,
    action: ApplyPatchAction,
    worktree: Path,
    window: dict[str, Any],
    task_dir: Path | None,
) -> Observation | CommandResult:
    task = _task_row(conn, task_id)
    _require_matching_fingerprint(
        conn,
        task=task,
        envelope=envelope,
        action=action,
        permit_id=window["permit_id"],
    )
    decision = recover(
        conn,
        task_id=task_id,
        workspace=worktree,
        expected_revision=task["state_revision"],
    )
    if decision == RecoverDecision.recorded_success:
        return Observation(body="already applied", truncated=False)
    if decision == RecoverDecision.recorded_error:
        return Observation(body="recovered error", truncated=False)
    if decision != RecoverDecision.retryable_same_attempt:
        raise ExecutionWindowOpenError(
            f"recovered window for task {task_id} is not retryable"
        )
    claim_id = claim_recovered_attempt(
        conn,
        task_id=task_id,
        window_id=window["window_id"],
        expected_revision=task["state_revision"],
        attempt_id=str(uuid.uuid4()),
    )
    try:
        return execute(
            conn,
            task_id=task_id,
            permit_id=window["permit_id"],
            window_id=window["window_id"],
            action=action,
            worktree=worktree,
            claim_id=claim_id,
            task_dir=task_dir,
            envelope=envelope,
        )
    except Exception:
        _fail_close_window(conn, task_id=task_id, window_id=window["window_id"])
        raise


def _set_task_state(
    conn: sqlite3.Connection, task_id: str, **fields: object
) -> None:
    task = _task_row(conn, task_id)
    update_task(conn, task_id, task["state_revision"], **fields)


def _sensor_verdict(profile: CommandProfile, result: CommandResult):
    sensor = profile.sensor
    if sensor == "junit_xml":
        expected = result.junit_path if result.junit_path is not None else ""
        return junit_xml_verdict(
            result,
            profile_id=profile.profile_id,
            expected_junit_path=expected,
        )
    if sensor == "exit_code":
        return exit_code_verdict(result, profile_id=profile.profile_id)
    return Verdict(
        profile_id=profile.profile_id,
        sensor="undeclared" if sensor is None else sensor,
        status=VerdictStatus.ERROR,
        exit_code=result.exit_code,
        summary=bounded_summary("undeclared or unknown sensor"),
        output_truncated=result.truncated,
        output_sha256=output_digest(result),
        duration_seconds=result.duration_seconds,
    )


def _after_verify_state(conn: sqlite3.Connection, task_id: str) -> str:
    remaining = _task_row(conn, task_id)["remaining_steps"]
    return "running" if remaining > 0 else "exhausted"


def _permit_then_execute(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    envelope: Envelope,
    action: RunCommandAction,
    worktree: Path,
    task_dir: Path | None,
    window_run_state: str,
) -> CommandResult | Observation:
    task = _task_row(conn, task_id)
    permit_id = create_permit(
        conn,
        task_id=task_id,
        action_id=str(uuid.uuid4()),
        fingerprint=_fingerprint(task, envelope, action),
        envelope_hash=envelope.envelope_hash,
        expected_revision=task["state_revision"],
    )
    task = _task_row(conn, task_id)
    window_id = consume_permit_and_open_window(
        conn,
        task_id=task_id,
        permit_id=permit_id,
        expected_revision=task["state_revision"],
        action_kind="run_command",
    )
    try:
        observation = execute(
            conn,
            task_id=task_id,
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=worktree,
            task_dir=task_dir,
            envelope=envelope,
        )
    except Exception:
        _fail_close_window(
            conn, task_id=task_id, window_id=window_id, run_state="error"
        )
        raise
    _complete_window(
        conn,
        task_id=task_id,
        window_id=window_id,
        run_state=window_run_state,
    )
    return observation


def _finish(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    envelope: Envelope,
    action: FinishAction,
    worktree: Path,
    task_dir: Path | None,
    patch_port: PatchArtifactPort | None,
) -> StepResult:
    task = _task_row(conn, task_id)
    if task["run_state"] != "running" or _active_window(conn, task_id) is not None:
        return StepResult(
            action=action, observation=None, run_state=task["run_state"]
        )
    if action.outcome == "failed":
        _set_task_state(conn, task_id, run_state="failed")
        return StepResult(action=action, observation=None, run_state="failed")
    if action.outcome == "blocked":
        _set_task_state(conn, task_id, run_state="blocked")
        return StepResult(action=action, observation=None, run_state="blocked")
    if action.outcome != "success":
        _set_task_state(conn, task_id, run_state="blocked")
        return StepResult(action=action, observation=None, run_state="blocked")

    plan = build_verify_plan(envelope)
    if not plan.verify_profile_ids:
        _set_task_state(conn, task_id, run_state="unverified")
        return StepResult(action=action, observation=None, run_state="unverified")

    _set_task_state(conn, task_id, run_state="verifying")
    profiles = {item.profile_id: item for item in envelope.profiles}
    all_pass = True
    last_observation: Observation | CommandResult | None = None
    fail_observation: Observation | None = None
    for profile_id in plan.verify_profile_ids:
        verify_action = RunCommandAction(action="run_command", profile_id=profile_id)
        task = _task_row(conn, task_id)
        verdict = evaluate(
            worktree=worktree,
            envelope=envelope,
            action=verify_action,
            budget=TaskBudget(remaining_steps=task["remaining_steps"]),
        )
        if verdict.kind is not VerdictKind.Allow:
            all_pass = False
            break
        last_observation = _permit_then_execute(
            conn,
            task_id=task_id,
            envelope=envelope,
            action=verify_action,
            worktree=worktree,
            task_dir=task_dir,
            window_run_state="verifying",
        )
        if not isinstance(last_observation, CommandResult):
            all_pass = False
            continue
        profile = profiles[profile_id]
        parsed = _sensor_verdict(profile, last_observation)
        if parsed.status is not VerdictStatus.PASS:
            all_pass = False
            fail_observation = Observation(
                body=parsed.model_dump_json(),
                truncated=False,
            )

    if all_pass:
        port = patch_port if patch_port is not None else StubPatchArtifactPort()
        task = _task_row(conn, task_id)
        artifact = port.export(
            SimpleNamespace(
                task_id=task_id,
                worktree_identity=task["worktree_identity"],
                base_commit=task["base_commit"],
                max_patch_bytes=1_000_000,
            )
        )
        if artifact.can_mark_patch_ready:
            _set_task_state(
                conn,
                task_id,
                run_state="succeeded",
                artifact_state="patch_ready",
            )
            return StepResult(
                action=action,
                observation=last_observation,
                run_state="succeeded",
            )
    next_state = _after_verify_state(conn, task_id)
    _set_task_state(conn, task_id, run_state=next_state)
    return StepResult(
        action=action,
        observation=fail_observation if fail_observation is not None else last_observation,
        run_state=next_state,
    )


def execute_approved(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    envelope: Envelope,
    pending_action_id: str,
    worktree: Path,
    task_dir: Path | None = None,
) -> StepResult:
    pending = conn.execute(
        "SELECT pending_action_id, fingerprint, normalized_action_json, "
        "state_revision, consumed FROM pending_actions "
        "WHERE pending_action_id = ?",
        (pending_action_id,),
    ).fetchone()
    if pending is None or not pending[4]:
        raise PermitInvalidError(
            f"pending action {pending_action_id} is not a consumed approval"
        )
    action = parse_llm_response(str(pending[2]))
    if isinstance(action, FinishAction) or type(action) not in _ACTION_KIND:
        raise PermitInvalidError("approved action cannot be executed")
    task = _task_row(conn, task_id)
    fingerprint = _fingerprint(task, envelope, action)
    if fingerprint != str(pending[1]):
        raise PermitInvalidError(
            f"fingerprint mismatch for approved action {pending_action_id}"
        )
    kind = _ACTION_KIND[type(action)]
    window = _active_window(conn, task_id)
    if (
        window is not None
        and window["execution_started"]
        and window["action_kind"] == "run_command"
    ):
        raise ExecutionWindowOpenError(
            f"refusing to auto-rerun started run_command for task {task_id}"
        )
    if (
        window is not None
        and isinstance(action, ApplyPatchAction)
        and window["execution_started"]
        and window["action_kind"] == "apply_patch"
    ):
        observation = _retry_started_patch(
            conn,
            task_id=task_id,
            envelope=envelope,
            action=action,
            worktree=worktree,
            window=window,
            task_dir=task_dir,
        )
        still = _active_window(conn, task_id)
        if still is not None and still["window_id"] == window["window_id"]:
            _complete_window(conn, task_id=task_id, window_id=window["window_id"])
        return StepResult(
            action=action,
            observation=observation,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if (
        window is not None
        and not window["execution_started"]
        and window["action_kind"] == kind
    ):
        _require_matching_fingerprint(
            conn,
            task=task,
            envelope=envelope,
            action=action,
            permit_id=window["permit_id"],
        )
        try:
            observation = execute(
                conn,
                task_id=task_id,
                permit_id=window["permit_id"],
                window_id=window["window_id"],
                action=action,
                worktree=worktree,
                task_dir=task_dir,
                envelope=envelope,
            )
        except Exception:
            _fail_close_window(
                conn, task_id=task_id, window_id=window["window_id"]
            )
            raise
        _complete_window(conn, task_id=task_id, window_id=window["window_id"])
        return StepResult(
            action=action,
            observation=observation,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if window is not None:
        raise ExecutionWindowOpenError(
            f"task {task_id} already has an active execution window"
        )

    preimage = postimage = None
    if isinstance(action, ApplyPatchAction):
        preimage, postimage = preview_patch(
            worktree, action.diff, allow_delete=envelope.allow_delete
        )
    permit_id = create_permit(
        conn,
        task_id=task_id,
        action_id=str(uuid.uuid4()),
        fingerprint=fingerprint,
        envelope_hash=envelope.envelope_hash,
        expected_revision=task["state_revision"],
        pending_action_id=pending_action_id,
    )
    task = _task_row(conn, task_id)
    window_id = consume_permit_and_open_window(
        conn,
        task_id=task_id,
        permit_id=permit_id,
        expected_revision=task["state_revision"],
        action_kind=kind,
        preimage=preimage,
        postimage=postimage,
    )
    try:
        observation = execute(
            conn,
            task_id=task_id,
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=worktree,
            task_dir=task_dir,
            envelope=envelope,
        )
    except Exception:
        _fail_close_window(conn, task_id=task_id, window_id=window_id)
        raise
    _complete_window(conn, task_id=task_id, window_id=window_id)
    return StepResult(
        action=action,
        observation=observation,
        run_state=_task_row(conn, task_id)["run_state"],
    )


def step(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    envelope: Envelope,
    llm: LLMPort,
    worktree: Path,
    task_description: str = "",
    observations: Sequence[object] = (),
    memories: Sequence[object] = (),
    task_dir: Path | None = None,
    patch_port: PatchArtifactPort | None = None,
) -> StepResult:
    task = _task_row(conn, task_id)
    budget = TaskBudget(remaining_steps=task["remaining_steps"])
    messages = build_context(
        task_description=task_description,
        envelope=envelope,
        budget=budget,
        observations=observations,
        memories=memories,
    )
    action = parse_llm_response(llm.complete(messages))
    verdict = evaluate(
        worktree=worktree,
        envelope=envelope,
        action=action,
        budget=budget,
    )
    if verdict.kind is VerdictKind.NeedApproval:
        _hitl(conn, task=task, envelope=envelope, action=action)
        return StepResult(
            action=action,
            observation=None,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if verdict.kind is VerdictKind.NeedEnvelopeRevision:
        update_task(
            conn,
            task_id,
            task["state_revision"],
            run_state="awaiting_envelope_revision",
        )
        return StepResult(
            action=action,
            observation=None,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if isinstance(action, FinishAction):
        return _finish(
            conn,
            task_id=task_id,
            envelope=envelope,
            action=action,
            worktree=worktree,
            task_dir=task_dir,
            patch_port=patch_port,
        )
    if verdict.kind is VerdictKind.Deny:
        return StepResult(
            action=action,
            observation=None,
            run_state=task["run_state"],
        )

    window = _active_window(conn, task_id)
    kind = _ACTION_KIND[type(action)]
    if (
        window is not None
        and isinstance(action, ApplyPatchAction)
        and window["execution_started"]
        and window["action_kind"] == "apply_patch"
    ):
        observation = _retry_started_patch(
            conn,
            task_id=task_id,
            envelope=envelope,
            action=action,
            worktree=worktree,
            window=window,
            task_dir=task_dir,
        )
        still = _active_window(conn, task_id)
        if still is not None and still["window_id"] == window["window_id"]:
            _complete_window(conn, task_id=task_id, window_id=window["window_id"])
        return StepResult(
            action=action,
            observation=observation,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if (
        window is not None
        and not window["execution_started"]
        and window["action_kind"] == kind
    ):
        _require_matching_fingerprint(
            conn,
            task=task,
            envelope=envelope,
            action=action,
            permit_id=window["permit_id"],
        )
        try:
            observation = execute(
                conn,
                task_id=task_id,
                permit_id=window["permit_id"],
                window_id=window["window_id"],
                action=action,
                worktree=worktree,
                task_dir=task_dir,
                envelope=envelope,
            )
        except Exception:
            _fail_close_window(
                conn, task_id=task_id, window_id=window["window_id"]
            )
            raise
        _complete_window(conn, task_id=task_id, window_id=window["window_id"])
        return StepResult(
            action=action,
            observation=observation,
            run_state=_task_row(conn, task_id)["run_state"],
        )
    if (
        window is not None
        and window["execution_started"]
        and window["action_kind"] != "apply_patch"
    ):
        task = _task_row(conn, task_id)
        decision = recover(
            conn,
            task_id=task_id,
            workspace=worktree,
            expected_revision=task["state_revision"],
        )
        if decision == RecoverDecision.recorded_error:
            return StepResult(
                action=action,
                observation=None,
                run_state=_task_row(conn, task_id)["run_state"],
            )
    if window is not None:
        raise ExecutionWindowOpenError(
            f"task {task_id} already has an active execution window"
        )

    preimage = postimage = None
    if isinstance(action, ApplyPatchAction):
        preimage, postimage = preview_patch(
            worktree, action.diff, allow_delete=envelope.allow_delete
        )
    permit_id = create_permit(
        conn,
        task_id=task_id,
        action_id=str(uuid.uuid4()),
        fingerprint=_fingerprint(task, envelope, action),
        envelope_hash=envelope.envelope_hash,
        expected_revision=task["state_revision"],
    )
    task = _task_row(conn, task_id)
    window_id = consume_permit_and_open_window(
        conn,
        task_id=task_id,
        permit_id=permit_id,
        expected_revision=task["state_revision"],
        action_kind=kind,
        preimage=preimage,
        postimage=postimage,
    )
    try:
        observation = execute(
            conn,
            task_id=task_id,
            permit_id=permit_id,
            window_id=window_id,
            action=action,
            worktree=worktree,
            task_dir=task_dir,
            envelope=envelope,
        )
    except Exception:
        _fail_close_window(conn, task_id=task_id, window_id=window_id)
        raise
    _complete_window(conn, task_id=task_id, window_id=window_id)
    return StepResult(
        action=action,
        observation=observation,
        run_state=_task_row(conn, task_id)["run_state"],
    )
