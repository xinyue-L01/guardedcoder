from __future__ import annotations

import json
import os
import sys
import uuid
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from guardedcoder.config.commands import resolve_config_path
from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.errors import (
    ApprovalError,
    ConfigError,
    ExecutionWindowOpenError,
    PendingConsumedError,
    PermitInvalidError,
    StaleRevisionError,
)
from guardedcoder.llm.openai_compat import OpenAICompatibleLLM
from guardedcoder.loop.engine import execute_approved, step
from guardedcoder.memory.store import (
    MemoryValidationError,
    add_constraint,
    add_decision,
    clear_repo,
    export_records,
    list_records,
)
from guardedcoder.models.config import AppConfig
from guardedcoder.models.envelope import Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.persist.approval import approve, reject
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task, update_task
from guardedcoder.persist.txn import write_txn
from guardedcoder.workspace.apply_back import (
    ApplyBackError,
    ApplyRecoverDecision,
    confirm_apply,
    preview_apply,
    recover_apply,
)
from guardedcoder.workspace.artifact import GitPatchArtifactPort
from guardedcoder.workspace.discard import discard_owned_worktree
from guardedcoder.workspace.gitops import DirtyWorktreeError, assert_clean, git_text
from guardedcoder.workspace.worktree import (
    OwnershipError,
    create_task_worktree,
    load_ownership,
)

_PAUSED = frozenset({"awaiting_approval", "awaiting_envelope_revision"})
_OK_STOP = frozenset({"succeeded", "unverified", *_PAUSED})
_USER_MEMORY_TYPES = {
    "constraint": "constraint",
    "project_constraint": "constraint",
    "decision": "decision",
}


class LifecycleError(RuntimeError):
    """Raised when product CLI orchestration fails closed."""


def default_harness_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "guardedcoder"


def format_effective_envelope(config: AppConfig, envelope: Envelope) -> str:
    profiles = ", ".join(
        f"{item.profile_id}={' '.join(item.argv_template)}"
        for item in envelope.profiles
    )
    return "\n".join(
        [
            f"endpoint: {config.provider.base_url}",
            "data types that may leave the machine: "
            "task description, selected source, memory, observations",
            f"read_paths: {list(envelope.read_paths)}",
            f"write_paths: {list(envelope.write_paths)}",
            f"profiles: {profiles}",
            f"verify_profiles: {list(envelope.verify_profiles)}",
            f"budget: max_steps={envelope.max_steps} "
            f"max_total_seconds={envelope.max_total_seconds}",
            f"allow_network: {str(envelope.allow_network).lower()}",
            f"allow_delete: {str(envelope.allow_delete).lower()}",
            f"envelope_hash: {envelope.envelope_hash}",
        ]
    )


def handle_command(
    args: Namespace,
    *,
    getpass_fn: Callable[..., str] | None = None,
    key_store: object | None = None,
    config_path: Path | str | None = None,
    llm: object | None = None,
    harness_dir: Path | str | None = None,
) -> int:
    del getpass_fn
    harness = _resolve_harness(args, harness_dir)
    config_file = _resolve_config(args, config_path)
    command = args.command
    try:
        if command == "run":
            return _handle_run(
                args,
                config_file=config_file,
                harness=harness,
                llm=llm,
                key_store=key_store,
            )
        if command == "approve":
            return _handle_approve(args, harness=harness)
        if command == "reject":
            return _handle_reject(args, harness=harness)
        if command == "resume":
            return _handle_resume(
                args,
                config_file=config_file,
                harness=harness,
                llm=llm,
                key_store=key_store,
            )
        if command == "apply":
            return _handle_apply(args, harness=harness)
        if command == "discard":
            return _handle_discard(args, harness=harness)
        if command == "memory":
            return _handle_memory(args, harness=harness)
        raise ConfigError(f"unknown command {command}")
    except (
        LifecycleError,
        ConfigError,
        DirtyWorktreeError,
        OwnershipError,
        ApprovalError,
        PendingConsumedError,
        PermitInvalidError,
        ExecutionWindowOpenError,
        ApplyBackError,
        MemoryValidationError,
        StaleRevisionError,
    ) as exc:
        print(str(exc))
        return 1


def _resolve_harness(args: Namespace, injected: Path | str | None) -> Path:
    raw = getattr(args, "harness_dir", None) or injected
    return Path(raw).expanduser().resolve() if raw else default_harness_dir()


def _resolve_config(args: Namespace, injected: Path | str | None) -> Path:
    raw = getattr(args, "config", None) or injected
    return resolve_config_path(raw)


def _db_path(harness: Path) -> Path:
    return harness / "guardedcoder.db"


def _connect(harness: Path):
    harness.mkdir(parents=True, exist_ok=True)
    return connect(_db_path(harness))


def _build_llm(config: AppConfig, key_store: object | None, llm: object | None):
    if llm is not None:
        return llm
    store = key_store
    if store is None:
        from guardedcoder.auth.keyring_store import KeyringStore

        store = KeyringStore()
    provider_id = config.provider.provider_id
    return OpenAICompatibleLLM(
        base_url=config.provider.base_url,
        model=config.provider.model,
        key_provider=lambda: store.get(provider_id),
    )


def _patch_port(harness: Path) -> GitPatchArtifactPort:
    return GitPatchArtifactPort(artifact_dir=harness / "artifacts")


def _task_row(conn, task_id: str):
    conn.row_factory = None
    row = conn.execute(
        "SELECT task_id, run_state, artifact_state, repo_path, base_commit, "
        "worktree_identity, envelope_hash, state_revision, remaining_steps "
        "FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise LifecycleError(f"task {task_id} not found")
    return {
        "task_id": row[0],
        "run_state": row[1],
        "artifact_state": row[2],
        "repo_path": row[3],
        "base_commit": row[4],
        "worktree_identity": row[5],
        "envelope_hash": row[6],
        "state_revision": int(row[7]),
        "remaining_steps": int(row[8]),
    }


def _save_envelope(conn, task_id: str, envelope: Envelope) -> None:
    payload = envelope.model_dump(mode="json", exclude={"envelope_hash"})
    with write_txn(conn):
        conn.execute(
            "INSERT INTO envelope_versions "
            "(envelope_hash, task_id, snapshot_json) VALUES (?, ?, ?)",
            (
                envelope.envelope_hash,
                task_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return {key: _freeze(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _load_envelope(conn, task_id: str, envelope_hash: str) -> Envelope:
    row = conn.execute(
        "SELECT snapshot_json FROM envelope_versions "
        "WHERE task_id = ? AND envelope_hash = ?",
        (task_id, envelope_hash),
    ).fetchone()
    if row is None:
        raise LifecycleError("stored envelope snapshot mismatch")
    payload = json.loads(str(row[0]))
    payload.pop("envelope_hash", None)
    return Envelope.model_validate(_freeze(payload))


def _set_error(conn, task_id: str) -> None:
    try:
        task = _task_row(conn, task_id)
        if task["run_state"] != "error":
            update_task(conn, task_id, task["state_revision"], run_state="error")
    except (LifecycleError, StaleRevisionError):
        return


def _pending_for(conn, task_id: str, fingerprint: str | None = None):
    if fingerprint is None:
        return conn.execute(
            "SELECT pending_action_id, fingerprint, state_revision, consumed "
            "FROM pending_actions WHERE task_id = ? ORDER BY rowid DESC",
            (task_id,),
        ).fetchone()
    return conn.execute(
        "SELECT pending_action_id, fingerprint, state_revision, consumed "
        "FROM pending_actions WHERE task_id = ? AND fingerprint = ? "
        "ORDER BY rowid DESC",
        (task_id, fingerprint),
    ).fetchone()


def _print_hitl(task_id: str, fingerprint: str, action: object | None = None) -> None:
    summary = ""
    if action is not None:
        dumped = getattr(action, "model_dump", lambda **_k: {"action": str(action)})(
            mode="json"
        )
        summary = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
    print(f"task_id: {task_id}")
    print("risk: NeedApproval")
    print(f"summary: {summary}")
    print(f"fingerprint: {fingerprint}")


def _save_runtime(
    conn,
    task_id: str,
    *,
    task_description: str,
    observations: list[object] | None = None,
    memories: list[object] | None = None,
) -> None:
    obs_payload = []
    for item in observations or ():
        if hasattr(item, "model_dump"):
            obs_payload.append(item.model_dump(mode="json"))
        else:
            obs_payload.append({"body": str(item), "truncated": False})
    mem_payload = []
    for item in memories or ():
        if hasattr(item, "model_dump"):
            mem_payload.append(item.model_dump(mode="json"))
        else:
            mem_payload.append({"content": str(item)})
    with write_txn(conn):
        conn.execute(
            "INSERT INTO task_runtime ("
            "task_id, task_description, observations_json, memories_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET "
            "task_description = excluded.task_description, "
            "observations_json = excluded.observations_json, "
            "memories_json = excluded.memories_json",
            (
                task_id,
                task_description,
                json.dumps(obs_payload, ensure_ascii=False),
                json.dumps(mem_payload, ensure_ascii=False),
            ),
        )


def _load_runtime(conn, task_id: str) -> tuple[str, tuple[Observation, ...], tuple[object, ...]]:
    row = conn.execute(
        "SELECT task_description, observations_json, memories_json "
        "FROM task_runtime WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return "", (), ()
    observations = []
    for item in json.loads(str(row[1]) or "[]"):
        if isinstance(item, dict) and "body" in item:
            observations.append(
                Observation(
                    body=str(item["body"]),
                    truncated=bool(item.get("truncated", False)),
                )
            )
    memories = tuple(json.loads(str(row[2]) or "[]"))
    return str(row[0] or ""), tuple(observations), memories


def _as_observation(item: object) -> Observation:
    if isinstance(item, Observation):
        return item
    body = getattr(item, "body", None)
    if body is None:
        body = getattr(item, "stdout", str(item))
    return Observation(
        body=str(body),
        truncated=bool(getattr(item, "truncated", False)),
    )


def _append_observation(conn, task_id: str, observation: object) -> None:
    description, observations, memories = _load_runtime(conn, task_id)
    _save_runtime(
        conn,
        task_id,
        task_description=description,
        observations=[*observations, _as_observation(observation)],
        memories=list(memories),
    )


def _run_steps(
    conn,
    *,
    task_id: str,
    envelope: Envelope,
    llm: object,
    worktree: Path,
    task_description: str,
    harness: Path,
) -> str:
    port = _patch_port(harness)
    task_dir = harness / "tasks" / task_id
    cap = max(_task_row(conn, task_id)["remaining_steps"], 1) + 1
    last_state = _task_row(conn, task_id)["run_state"]
    description, observations, memories = _load_runtime(conn, task_id)
    if not description:
        description = task_description
    for _ in range(cap):
        task = _task_row(conn, task_id)
        if task["run_state"] != "running":
            return task["run_state"]
        result = step(
            conn,
            task_id=task_id,
            envelope=envelope,
            llm=llm,
            worktree=worktree,
            task_description=description,
            observations=observations,
            memories=memories,
            task_dir=task_dir,
            patch_port=port,
        )
        last_state = result.run_state
        if result.observation is not None:
            _append_observation(conn, task_id, result.observation)
            description, observations, memories = _load_runtime(conn, task_id)
        if result.run_state in _PAUSED:
            pending = _pending_for(conn, task_id)
            if pending is not None:
                _print_hitl(task_id, str(pending[1]), result.action)
            return result.run_state
        if result.run_state != "running":
            return result.run_state
        if result.observation is None:
            _set_error(conn, task_id)
            return "error"
    _set_error(conn, task_id)
    return last_state


def _handle_run(
    args: Namespace,
    *,
    config_file: Path,
    harness: Path,
    llm: object | None,
    key_store: object | None,
) -> int:
    config = load_app_config(config_file)
    overrides = {}
    max_steps = getattr(args, "max_steps", None)
    if max_steps is not None:
        overrides["max_steps"] = max_steps
    envelope = synthesize_envelope(config, overrides or None)
    print(format_effective_envelope(config, envelope))
    confirmed = getattr(args, "confirm_envelope_hash", None)
    if not confirmed:
        return 1
    if confirmed != envelope.envelope_hash:
        print("envelope hash mismatch")
        return 1
    repo = getattr(args, "repo", None)
    if not repo:
        raise LifecycleError("run requires --repo")
    origin = assert_clean(repo)
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    base_commit = git_text(origin, "rev-parse", "HEAD")
    ownership = create_task_worktree(
        task_id=task_id,
        repo_path=origin,
        base_commit=base_commit,
        harness_dir=harness,
    )
    conn = _connect(harness)
    create_task(
        conn,
        task_id=task_id,
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(origin),
        base_commit=ownership.base_commit,
        worktree_identity=str(ownership.worktree_path),
        envelope_hash=envelope.envelope_hash,
        remaining_steps=envelope.max_steps,
    )
    _save_envelope(conn, task_id, envelope)
    task_description = getattr(args, "task", "") or ""
    _save_runtime(conn, task_id, task_description=task_description)
    print(f"task_id: {task_id}")
    state = _run_steps(
        conn,
        task_id=task_id,
        envelope=envelope,
        llm=_build_llm(config, key_store, llm),
        worktree=ownership.worktree_path,
        task_description=task_description,
        harness=harness,
    )
    return 0 if state in _OK_STOP else 1


def _handle_approve(args: Namespace, *, harness: Path) -> int:
    conn = _connect(harness)
    approve(conn, args.task_id, args.fingerprint)
    print(f"approved: {args.task_id}")
    return 0


def _handle_reject(args: Namespace, *, harness: Path) -> int:
    conn = _connect(harness)
    reject(conn, args.task_id, args.fingerprint)
    _append_observation(
        conn,
        args.task_id,
        Observation(body="rejected: action denied by user", truncated=False),
    )
    print(f"rejected: {args.task_id}")
    return 0


def _verify_resume(conn, *, task_id: str, fingerprint: str, harness: Path) -> dict:
    task = _task_row(conn, task_id)
    pending = _pending_for(conn, task_id, fingerprint)
    if pending is None:
        raise LifecycleError("pending fingerprint mismatch")
    pending_id, stored_fp, bound_revision, consumed = pending
    del pending_id, stored_fp
    if not consumed:
        raise LifecycleError("pending action not consumed")
    if int(bound_revision) not in {task["state_revision"], task["state_revision"] - 1}:
        raise LifecycleError("state_revision mismatch")
    snapshot = _load_envelope(conn, task_id, task["envelope_hash"])
    if snapshot.envelope_hash != task["envelope_hash"]:
        raise LifecycleError("envelope hash mismatch")
    ownership = load_ownership(task_id, harness_dir=harness)
    if ownership.base_commit != task["base_commit"]:
        raise LifecycleError("base commit mismatch")
    if str(ownership.worktree_path) != task["worktree_identity"]:
        raise LifecycleError("worktree ownership mismatch")
    window = conn.execute(
        "SELECT action_kind, execution_started, status FROM execution_windows "
        "WHERE task_id = ? AND status = ? ORDER BY rowid DESC",
        (task_id, "executing_action"),
    ).fetchone()
    if (
        window is not None
        and window[0] == "run_command"
        and bool(window[1])
    ):
        raise LifecycleError("refusing to auto-rerun started run_command")
    del consumed
    return task


def _handle_resume(
    args: Namespace,
    *,
    config_file: Path,
    harness: Path,
    llm: object | None,
    key_store: object | None,
) -> int:
    conn = _connect(harness)
    task_id = args.task_id
    try:
        task = _verify_resume(
            conn, task_id=task_id, fingerprint=args.fingerprint, harness=harness
        )
    except (
        LifecycleError,
        OwnershipError,
        ApprovalError,
        StaleRevisionError,
    ) as exc:
        _set_error(conn, task_id)
        print(str(exc))
        return 1
    envelope = _load_envelope(conn, task_id, task["envelope_hash"])
    pending = _pending_for(conn, task_id, args.fingerprint)
    if pending is None:
        _set_error(conn, task_id)
        print("pending fingerprint mismatch")
        return 1
    if task["run_state"] in {"awaiting_approval", "executing_action"}:
        result = execute_approved(
            conn,
            task_id=task_id,
            envelope=envelope,
            pending_action_id=str(pending[0]),
            worktree=Path(task["worktree_identity"]),
            task_dir=harness / "tasks" / task_id,
        )
        if result.observation is not None:
            _append_observation(conn, task_id, result.observation)
        return 0 if result.run_state in (_OK_STOP | {"running"}) else 1
    already = conn.execute(
        "SELECT 1 FROM permits WHERE pending_action_id = ?",
        (pending[0],),
    ).fetchone()
    if already is not None:
        raise LifecycleError("approved action already executed")
    config = load_app_config(config_file)
    description, observations, memories = _load_runtime(conn, task_id)
    result = step(
        conn,
        task_id=task_id,
        envelope=envelope,
        llm=_build_llm(config, key_store, llm),
        worktree=Path(task["worktree_identity"]),
        task_description=description,
        observations=observations,
        memories=memories,
        task_dir=harness / "tasks" / task_id,
        patch_port=_patch_port(harness),
    )
    if result.observation is not None:
        _append_observation(conn, task_id, result.observation)
    if result.run_state in _PAUSED:
        nxt = _pending_for(conn, task_id)
        if nxt is not None:
            _print_hitl(task_id, str(nxt[1]), result.action)
    return 0 if result.run_state in (_OK_STOP | {"running"}) else 1


def _handle_apply(args: Namespace, *, harness: Path) -> int:
    conn = _connect(harness)
    task = _task_row(conn, args.task_id)
    origin = Path(task["repo_path"])
    if task["artifact_state"] == "applying":
        decision = recover_apply(
            conn,
            task_id=args.task_id,
            expected_revision=task["state_revision"],
            origin=origin,
        )
        if decision is ApplyRecoverDecision.applied:
            print("applied")
            return 0
        if decision is ApplyRecoverDecision.needs_reconfirm:
            print("needs_reconfirm")
            return 1
        print("cleanup_error: origin may be partially changed")
        return 1
    port = _patch_port(harness)
    artifact = port.export(
        SimpleNamespace(
            task_id=args.task_id,
            worktree_identity=task["worktree_identity"],
            base_commit=task["base_commit"],
            max_patch_bytes=1_000_000,
        )
    )
    preview = preview_apply(
        conn,
        task_id=args.task_id,
        expected_revision=task["state_revision"],
        artifact=artifact,
    )
    print(preview.summary)
    print(f"fingerprint: {preview.fingerprint}")
    if not getattr(args, "confirm", False):
        return 0
    confirm_apply(conn, preview, confirmed=True)
    print("applied")
    return 0


def _handle_discard(args: Namespace, *, harness: Path) -> int:
    conn = _connect(harness)
    task = _task_row(conn, args.task_id)
    discard_owned_worktree(args.task_id, harness_dir=harness)
    update_task(
        conn,
        args.task_id,
        task["state_revision"],
        artifact_state="discarded",
    )
    print(f"discarded: {args.task_id}")
    return 0


def _handle_memory(args: Namespace, *, harness: Path) -> int:
    action = args.memory_command
    repo_id = getattr(args, "repo_id", None)
    if action == "clear" and not repo_id:
        raise LifecycleError("memory clear requires --repo-id")
    if not repo_id:
        raise LifecycleError("memory commands require --repo-id")
    conn = _connect(harness)
    if action == "add":
        record_type = _USER_MEMORY_TYPES.get(args.type)
        if record_type is None:
            raise LifecycleError("users may only write project_constraint or decision")
        paths = tuple(getattr(args, "path", None) or ())
        tags = tuple(getattr(args, "tag", None) or ())
        try:
            if record_type == "constraint":
                record = add_constraint(
                    conn,
                    repo_id=repo_id,
                    content=args.content,
                    paths=paths,
                    tags=tags,
                )
            else:
                record = add_decision(
                    conn,
                    repo_id=repo_id,
                    content=args.content,
                    rationale=getattr(args, "rationale", None),
                    paths=paths,
                    tags=tags,
                )
        except MemoryValidationError as exc:
            print(str(exc))
            return 1
        print(f"added: {record.record_id}")
        return 0
    if action == "list":
        records = list_records(conn, repo_id)
        for record in records:
            print(f"{record.record_type}: {record.content}")
        return 0
    if action == "export":
        print(export_records(conn, repo_id))
        return 0
    if action == "clear":
        deleted = clear_repo(conn, repo_id)
        print(f"cleared: {deleted}")
        return 0
    raise LifecycleError(f"unknown memory command {action}")
