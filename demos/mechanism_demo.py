"""Offline deterministic mechanism demo: four scenes, bounded output."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.config.template import DEFAULT_CONFIG_TOML
from guardedcoder.errors import (
    ActionParseError,
    ApprovalError,
    ConfigError,
    PendingConsumedError,
    PermitConsumedError,
)
from guardedcoder.fingerprint import SCHEMA_VERSION, compute_fingerprint
from guardedcoder.governance.classify import classify_write
from guardedcoder.governance.evaluate import VerdictKind, evaluate
from guardedcoder.llm.mock import MockLLM
from guardedcoder.loop.engine import step
from guardedcoder.models.actions import (
    ApplyPatchAction,
    FinishAction,
    ListDirAction,
    ReadFileAction,
    RunCommandAction,
    parse_llm_response,
)
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.models.observation import Observation
from guardedcoder.models.permit import RiskDecision
from guardedcoder.models.task import TaskBudget
from guardedcoder.models.verdict import Verdict, VerdictStatus
from guardedcoder.persist.approval import approve, request_approval
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.persist.store import create_task
from guardedcoder.tools.executor import execute

_MAX_CHARS = 8192


class _SpyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *args: object, **kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("executor must not rerun")


def _envelope(
    *,
    write_paths: tuple[str, ...] = ("src",),
    read_paths: tuple[str, ...] = ("src",),
    profiles: tuple[CommandProfile, ...] = (),
) -> Envelope:
    return Envelope(
        read_paths=read_paths,
        write_paths=write_paths,
        profiles=profiles,
        verify_profiles=tuple(p.profile_id for p in profiles),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="demo",
    )


def _pytest_profile() -> CommandProfile:
    return CommandProfile(
        profile_id="pytest",
        argv_template=["pytest", "--junitxml", "{junit_out}"],
        cwd=".",
        timeout_seconds=60,
        max_output_bytes=65536,
    )


def _forbidden_profile() -> CommandProfile:
    return CommandProfile(
        profile_id="deps",
        argv_template=["pip", "install", "pkg"],
        cwd=".",
        timeout_seconds=60,
        max_output_bytes=65536,
    )


def _boot(conn: sqlite3.Connection, workspace: Path, envelope: Envelope, task_id: str) -> None:
    create_task(
        conn,
        task_id=task_id,
        run_state="running",
        artifact_state="worktree_present",
        repo_path=str(workspace),
        base_commit="abc",
        worktree_identity=str(workspace.resolve()),
        envelope_hash=envelope.envelope_hash,
        remaining_steps=10,
    )


def _task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        raise LookupError(task_id)
    return row


def _fp(conn: sqlite3.Connection, envelope: Envelope, action: object, task_id: str) -> str:
    task = _task(conn, task_id)
    return compute_fingerprint(
        schema_version=SCHEMA_VERSION,
        task_id=task["task_id"],
        envelope_hash=envelope.envelope_hash,
        base_commit=task["base_commit"],
        worktree_identity=task["worktree_identity"],
        normalized_action=action.model_dump(mode="json"),
    )


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


def _scene_governance(root: Path) -> list[str]:
    ws = root / "gov"
    ws.mkdir(parents=True)
    (ws / "src").mkdir()
    (ws / "docs").mkdir()
    (ws / "docs" / "note.md").write_text("x", encoding="utf-8")
    (ws / ".env").write_text("x", encoding="utf-8")
    env = _envelope(profiles=(_pytest_profile(),))
    budget = TaskBudget(remaining_steps=10)

    unknown = "schema_ok"
    try:
        parse_llm_response('{"action":"curl"}')
    except ActionParseError:
        unknown = "schema_reject"

    escape = evaluate(
        worktree=ws,
        envelope=env,
        action=ReadFileAction(action="read_file", path="../secret"),
        budget=budget,
    )
    sensitive = evaluate(
        worktree=ws,
        envelope=env,
        action=ReadFileAction(action="read_file", path=".env"),
        budget=budget,
    )
    forbidden = evaluate(
        worktree=ws,
        envelope=_envelope(profiles=(_forbidden_profile(),)),
        action=RunCommandAction(action="run_command", profile_id="deps"),
        budget=budget,
    )
    hitl = classify_write(ws, env, "docs/note.md")

    assert unknown == "schema_reject"
    assert escape.kind is VerdictKind.Deny and escape.code == "WORKSPACE_ESCAPE"
    assert sensitive.kind is VerdictKind.Deny and sensitive.code == "SENSITIVE_PATH"
    assert forbidden.kind is VerdictKind.Deny and forbidden.code == "HARD_FORBIDDEN_COMMAND"
    assert hitl.decision is RiskDecision.NeedApproval
    return [
        "SCENE 1 governance",
        "unknown_action: schema_reject",
        "workspace_escape: deny WORKSPACE_ESCAPE",
        "sensitive_path: deny SENSITIVE_PATH",
        "hard_forbidden: deny HARD_FORBIDDEN_COMMAND",
        "in_tree_write_outside_range: hitl NeedApproval",
    ]


def _scene_fail_loop(root: Path) -> list[str]:
    def _run(label: str, with_fail: bool) -> tuple[str, str, str, object]:
        ws = root / label
        ws.mkdir(parents=True)
        (ws / "a.txt").write_bytes(b"before\n")
        envelope = _envelope(write_paths=(".",), read_paths=(".",))
        conn = connect(ws / "g.db")
        _boot(conn, ws, envelope, "t1")
        llm = MockLLM(
            responses=[_patch_json("before", "after"), _patch_json("after", "fixed")],
            gate_on_fail=True,
        )
        assert llm._gate_on_fail is True
        first = step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=llm,
            worktree=ws,
            task_description="offline demo",
        )
        assert isinstance(first.action, ApplyPatchAction)
        first_fp = _fp(conn, envelope, first.action, "t1")
        observations = []
        if with_fail:
            observations = [Observation(body=_fail_verdict_text(), truncated=False)]
        else:
            observations = [Observation(body="tests still running", truncated=False)]
        second = step(
            conn,
            task_id="t1",
            envelope=envelope,
            llm=llm,
            worktree=ws,
            task_description="offline demo",
            observations=observations,
        )
        second_fp = _fp(conn, envelope, second.action, "t1")
        conn.close()
        return type(second.action).__name__, second_fp, first_fp, second.action

    blocked_kind, blocked_fp, first_fp, blocked_action = _run("fail_a", False)
    assert blocked_kind == "FinishAction"
    assert isinstance(blocked_action, FinishAction)
    assert blocked_action.outcome in {"blocked", "failed"}
    assert blocked_fp != first_fp

    corr_kind, corr_fp, orig_fp, corr_action = _run("fail_b", True)
    assert corr_kind == "ApplyPatchAction"
    assert isinstance(corr_action, ApplyPatchAction)
    assert corr_fp != orig_fp
    return [
        "SCENE 2 fail_loop",
        "gate_on_fail: true",
        "before_fail: blocked no_correction_patch",
        "after_fail: correction_patch fingerprint_changed",
    ]


def _scene_permit_window(root: Path) -> list[str]:
    ws = root / "permit"
    ws.mkdir(parents=True)
    (ws / "src").mkdir()
    envelope = _envelope(write_paths=(".",), read_paths=(".",), profiles=(_pytest_profile(),))
    conn = connect(ws / "g.db")
    _boot(conn, ws, envelope, "hitl")
    action = ListDirAction(action="list_dir", path=".")
    fp = _fp(conn, envelope, action, "hitl")
    request_approval(
        conn,
        task_id="hitl",
        fingerprint=fp,
        normalized_action_json=json.dumps(action.model_dump(mode="json")),
        expected_revision=1,
    )
    wrong = "refuse_missing"
    try:
        approve(conn, "hitl", "0" * 64)
    except ApprovalError:
        wrong = "refuse"
    approve(conn, "hitl", fp)
    replay = "accept"
    try:
        approve(conn, "hitl", fp)
    except PendingConsumedError:
        replay = "refuse"

    _boot(conn, ws, envelope, "perm")
    permit_id = create_permit(
        conn,
        task_id="perm",
        action_id="a1",
        fingerprint="fp1",
        envelope_hash=envelope.envelope_hash,
        expected_revision=1,
    )
    consume_permit_and_open_window(
        conn,
        task_id="perm",
        permit_id=permit_id,
        expected_revision=2,
        action_kind="list_dir",
    )
    permit_replay = "accept"
    try:
        consume_permit_and_open_window(
            conn,
            task_id="perm",
            permit_id=permit_id,
            expected_revision=3,
            action_kind="list_dir",
        )
    except PermitConsumedError:
        permit_replay = "refuse"

    _boot(conn, ws, envelope, "happy")
    happy_action = ListDirAction(action="list_dir", path=".")
    verdict = evaluate(
        worktree=ws,
        envelope=envelope,
        action=happy_action,
        budget=TaskBudget(remaining_steps=10),
    )
    assert verdict.kind is VerdictKind.Allow
    happy_fp = _fp(conn, envelope, happy_action, "happy")
    happy_permit = create_permit(
        conn,
        task_id="happy",
        action_id="a2",
        fingerprint=happy_fp,
        envelope_hash=envelope.envelope_hash,
        expected_revision=1,
    )
    window_id = consume_permit_and_open_window(
        conn,
        task_id="happy",
        permit_id=happy_permit,
        expected_revision=2,
        action_kind="list_dir",
    )
    observation = execute(
        conn,
        task_id="happy",
        permit_id=happy_permit,
        window_id=window_id,
        action=happy_action,
        worktree=ws,
        envelope=envelope,
    )
    assert isinstance(observation, Observation)
    assert observation.body is not None

    crash_ws = root / "crash"
    crash_ws.mkdir(parents=True)
    crash_conn = connect(crash_ws / "g.db")
    crash_env = _envelope(write_paths=(".",), read_paths=(".",), profiles=(_pytest_profile(),))
    _boot(crash_conn, crash_ws, crash_env, "crash")
    crash_permit = create_permit(
        crash_conn,
        task_id="crash",
        action_id="a3",
        fingerprint="fp-crash",
        envelope_hash=crash_env.envelope_hash,
        expected_revision=1,
    )
    crash_window = consume_permit_and_open_window(
        crash_conn,
        task_id="crash",
        permit_id=crash_permit,
        expected_revision=2,
        action_kind="run_command",
    )
    crash_conn.execute(
        "UPDATE execution_windows SET execution_started = 1 WHERE window_id = ?",
        (crash_window,),
    )
    spy = _SpyExecutor()
    crash_task = _task(crash_conn, "crash")
    cmd_decision = recover(
        crash_conn,
        task_id="crash",
        workspace=crash_ws,
        expected_revision=crash_task["state_revision"],
        executor=spy,
    )
    assert cmd_decision is RecoverDecision.recorded_error
    assert spy.calls == 0

    patch_ws = root / "patch"
    patch_ws.mkdir(parents=True)
    before = b"before\n"
    after = b"after\n"
    (patch_ws / "a.txt").write_bytes(before)
    patch_conn = connect(patch_ws / "g.db")
    patch_env = _envelope(write_paths=(".",), read_paths=(".",))
    _boot(patch_conn, patch_ws, patch_env, "patch")
    patch_permit = create_permit(
        patch_conn,
        task_id="patch",
        action_id="a4",
        fingerprint="fp-patch",
        envelope_hash=patch_env.envelope_hash,
        expected_revision=1,
    )

    def _mark(body: bytes) -> dict[str, object]:
        return {"exists": True, "sha256": hashlib.sha256(body).hexdigest()}

    consume_permit_and_open_window(
        patch_conn,
        task_id="patch",
        permit_id=patch_permit,
        expected_revision=2,
        action_kind="apply_patch",
        preimage={"a.txt": _mark(before)},
        postimage={"a.txt": _mark(after)},
    )
    patch_task = _task(patch_conn, "patch")
    patch_decision = recover(
        patch_conn,
        task_id="patch",
        workspace=patch_ws,
        expected_revision=patch_task["state_revision"],
    )
    assert patch_decision is RecoverDecision.retryable_same_attempt
    conn.close()
    crash_conn.close()
    patch_conn.close()
    assert wrong == "refuse"
    assert replay == "refuse"
    assert permit_replay == "refuse"
    return [
        "SCENE 3 permit_window",
        "wrong_fingerprint: refuse",
        "old_approval_replay: refuse",
        "permit_replay: refuse",
        "happy_path: evaluate>create_permit>consume_open_window>execute>observation",
        "crash_recovery_run_command: fail_closed recorded_error no_rerun",
        "crash_recovery_apply_patch: retryable_same_attempt",
    ]


def _scene_illegal_toml(root: Path) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    base = DEFAULT_CONFIG_TOML

    def _refuse(name: str, body: str) -> str:
        path = root / f"{name}.toml"
        path.write_text(body, encoding="utf-8")
        try:
            load_app_config(path)
        except ConfigError:
            return f"{name}: refuse no_worktree no_llm"
        raise AssertionError(f"{name} was accepted")

    unknown = _refuse("unknown_key", base + "\nextra_field = true\n")
    secret = _refuse("secret_like", base + '\ntoken = "t"\n')
    shell = _refuse(
        "shell_string",
        base.replace(
            'cwd = "."\n',
            'cwd = "."\nshell = true\n',
        ),
    )
    forbidden = _refuse(
        "hard_forbidden_profile",
        base.replace(
            'argv_template = ["pytest", "--junitxml", "{junit_out}"]',
            'argv_template = ["pip", "install", "pkg"]',
        ),
    )
    wrong_type = _refuse(
        "wrong_type",
        base.replace("max_steps = 10", 'max_steps = "nope"'),
    )
    legal_path = root / "legal.toml"
    legal_path.write_text(base, encoding="utf-8")
    cfg = load_app_config(legal_path)
    first = synthesize_envelope(cfg)
    second = synthesize_envelope(cfg)
    assert first.envelope_hash == second.envelope_hash
    return [
        "SCENE 4 illegal_toml",
        unknown,
        secret,
        shell,
        forbidden,
        wrong_type,
        "legal_synthesize: identical_envelope_hash",
    ]


def run_all() -> str:
    lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gc-demo-") as raw:
        root = Path(raw)
        for name in ("s1", "s2", "s3", "s4"):
            (root / name).mkdir()
        lines.extend(_scene_governance(root / "s1"))
        lines.extend(_scene_fail_loop(root / "s2"))
        lines.extend(_scene_permit_window(root / "s3"))
        lines.extend(_scene_illegal_toml(root / "s4"))
    text = "\n".join(lines) + "\n"
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS - 16] + "\n...[truncated]\n"
    return text


def main() -> int:
    print(run_all(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
