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
    PendingConsumedError,
    StaleRevisionError,
)
from guardedcoder.llm.openai_compat import OpenAICompatibleLLM
from guardedcoder.loop.engine import step
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
from guardedcoder.persist.approval import approve, reject
from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task, update_task
from guardedcoder.persist.txn import write_txn
from guardedcoder.workspace.apply_back import (
    ApplyBackError,
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
_USER_MEMORY_TYPES = frozenset({"constraint", "decision"})


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
    return Envelope.model_validate(payload)


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


def _print_hitl(task_id: str, fingerprint: str) -> None:
    print(f"task_id: {task_id}")
    print(f"fingerprint: {fingerprint}")
    print("run_state: awaiting_approval")


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
            task_description=task_description,
            task_dir=task_dir,
            patch_port=port,
        )
        last_state = result.run_state
        if result.run_state in _PAUSED:
            pending = _pending_for(conn, task_id)
            if pending is not None:
                _print_hitl(task_id, str(pending[1]))
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
    print(f"task_id: {task_id}")
    state = _run_steps(
        conn,
        task_id=task_id,
        envelope=envelope,
        llm=_build_llm(config, key_store, llm),
        worktree=ownership.worktree_path,
        task_description=getattr(args, "task", "") or "",
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
    if task["run_state"] == "awaiting_approval":
        update_task(conn, task_id, task["state_revision"], run_state="running")
        task = _task_row(conn, task_id)
    envelope = _load_envelope(conn, task_id, task["envelope_hash"])
    config = load_app_config(config_file)
    state = _run_steps(
        conn,
        task_id=task_id,
        envelope=envelope,
        llm=_build_llm(config, key_store, llm),
        worktree=Path(task["worktree_identity"]),
        task_description="",
        harness=harness,
    )
    return 0 if state in _OK_STOP else 1


def _handle_apply(args: Namespace, *, harness: Path) -> int:
    conn = _connect(harness)
    task = _task_row(conn, args.task_id)
    origin = Path(task["repo_path"])
    if task["artifact_state"] == "applying":
        recover_apply(
            conn,
            task_id=args.task_id,
            expected_revision=task["state_revision"],
            origin=origin,
        )
        print("apply recovered")
        return 0
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
    discard_owned_worktree(args.task_id, harness_dir=harness)
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
        record_type = args.type
        if record_type not in _USER_MEMORY_TYPES:
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
