from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guardedcoder.errors import ExecutionWindowOpenError, StaleRevisionError
from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint
from guardedcoder.governance.evaluate import VerdictKind, evaluate
from guardedcoder.llm.port import LLMPort
from guardedcoder.loop.context import build_context
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
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.models.task import TaskBudget
from guardedcoder.persist.approval import request_approval
from guardedcoder.persist.claim import claim_recovered_attempt
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.persist.store import update_task
from guardedcoder.persist.txn import write_txn
from guardedcoder.tools.apply_patch import (
    _apply_hunks,
    _involved_paths,
    _mark_bytes,
    _parse_diff,
    _read_text,
)
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


def _images_for_patch(
    worktree: Path, diff: str
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    files = _parse_diff(diff)
    root = worktree.resolve()
    all_paths: list[str] = []
    planned: dict[str, bytes | None] = {}
    for file_patch in files:
        for rel in _involved_paths(file_patch):
            if rel not in all_paths:
                all_paths.append(rel)
        old_rel = file_patch.old_path
        new_rel = file_patch.new_path
        creating = old_rel is None
        deleting = new_rel is None
        renaming = (
            old_rel is not None and new_rel is not None and old_rel != new_rel
        )
        if creating:
            original = ""
        else:
            assert old_rel is not None
            original = _read_text(root / old_rel)
        updated = (
            _apply_hunks(original, file_patch.hunks) if file_patch.hunks else original
        )
        new_bytes = updated.encode("utf-8")
        if deleting:
            assert old_rel is not None
            planned[old_rel] = None
        elif renaming:
            assert old_rel is not None and new_rel is not None
            planned[new_rel] = new_bytes
            planned[old_rel] = None
        else:
            assert new_rel is not None
            planned[new_rel] = new_bytes
    preimage = {
        rel: _mark_bytes(
            None if not (root / rel).is_file() else (root / rel).read_bytes()
        )
        for rel in all_paths
    }
    postimage = {
        rel: _mark_bytes(planned[rel]) if rel in planned else preimage[rel]
        for rel in all_paths
    }
    return preimage, postimage


def _complete_window(
    conn: sqlite3.Connection, *, task_id: str, window_id: str
) -> None:
    task = _task_row(conn, task_id)
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET run_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ?",
            ("running", task_id, task["state_revision"]),
        )
        if cur.rowcount == 0:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {task['state_revision']}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            ("succeeded", window_id),
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
    decision = recover(
        conn,
        task_id=task_id,
        workspace=worktree,
        expected_revision=task["state_revision"],
    )
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
    if verdict.kind is VerdictKind.Deny or isinstance(action, FinishAction):
        return StepResult(
            action=action,
            observation=None,
            run_state=task["run_state"],
        )

    window = _active_window(conn, task_id)
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

    kind = _ACTION_KIND[type(action)]
    permit_id = create_permit(
        conn,
        task_id=task_id,
        action_id=str(uuid.uuid4()),
        fingerprint=_fingerprint(task, envelope, action),
        envelope_hash=envelope.envelope_hash,
        expected_revision=task["state_revision"],
    )
    task = _task_row(conn, task_id)
    preimage = postimage = None
    if isinstance(action, ApplyPatchAction):
        preimage, postimage = _images_for_patch(worktree, action.diff)
    window_id = consume_permit_and_open_window(
        conn,
        task_id=task_id,
        permit_id=permit_id,
        expected_revision=task["state_revision"],
        action_kind=kind,
        preimage=preimage,
        postimage=postimage,
    )
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
    _complete_window(conn, task_id=task_id, window_id=window_id)
    return StepResult(
        action=action,
        observation=observation,
        run_state=_task_row(conn, task_id)["run_state"],
    )
