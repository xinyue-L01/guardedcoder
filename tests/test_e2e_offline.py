from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from guardedcoder.cli import main
from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.errors import (
    ClaimConflictError,
    PendingConsumedError,
    PermitConsumedError,
)
from guardedcoder.governance.evaluate import VerdictKind, evaluate
from guardedcoder.llm.mock import MockLLM
from guardedcoder.models.actions import ApplyPatchAction, ListDirAction, ReadFileAction
from guardedcoder.models.task import TaskBudget
from guardedcoder.persist.claim import claim_recovered_attempt
from guardedcoder.persist.db import connect
from guardedcoder.persist.permit import consume_permit_and_open_window, create_permit
from guardedcoder.persist.recover import RecoverDecision, recover
from guardedcoder.workspace.apply_back import enter_applying, preview_apply
from guardedcoder.workspace.artifact import GitPatchArtifactPort

_SUCCESS_MARK = "E2E_OK"
_WRONG_APP = 'FLAG = "wrong"\n'
_FIXED_APP = f'FLAG = "{_SUCCESS_MARK}"\n'
_NOTES_BASE = "todo\n"
_NOTES_HITL = "reviewed\n"
_PLANTED_JUNIT = (
    '<?xml version="1.0"?><testsuite tests="1" failures="0" errors="0" skipped="0">'
    '<testcase classname="stale" name="old"/></testsuite>'
)
_VERIFY_SCRIPT = """\
from pathlib import Path
import sys

out = Path(sys.argv[1])
text = Path("src/app.py").read_text(encoding="utf-8")
ok = "E2E_OK" in text
failures = 0 if ok else 1
fail_xml = "" if ok else '<failure message="missing E2E_OK"/>'
out.write_text(
    '<?xml version="1.0"?>'
    f'<testsuite tests="1" failures="{failures}" errors="0" skipped="0">'
    f'<testcase classname="e2e" name="flag">{fail_xml}</testcase>'
    "</testsuite>",
    encoding="utf-8",
)
raise SystemExit(failures)
"""


class BoomLLM:
    def complete(self, messages: list[dict[str, str]]) -> str:
        raise AssertionError("LLM.complete must not be called")


class CaptureLLM:
    def __init__(self, inner: MockLLM) -> None:
        self.inner = inner
        self.calls: list[list[dict[str, str]]] = []
        self.responses: list[str] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        response = self.inner.complete(messages)
        self.responses.append(response)
        return response


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=GuardedCoder Tests",
            "-c",
            "user.email=guardedcoder-tests@example.invalid",
            "commit",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def _legal_toml(*, write_paths: str = '["src"]') -> str:
    exe = sys.executable.replace("\\", "/")
    return f"""\
config_schema_version = "1"
read_paths = ["src"]
write_paths = {write_paths}
verify_profiles = ["unit"]
max_steps = 10
max_total_seconds = 300
command_timeout_seconds = 60
max_output_bytes = 65536
max_patch_bytes = 1000000
allow_delete = false
allow_network = false

[provider]
provider_id = "openai-compat"
base_url = "http://127.0.0.1:8080/v1"
model = "local"
timeout_seconds = 30

[[profiles]]
profile_id = "unit"
argv_template = ["{exe}", "verify_junit.py", "{{junit_out}}"]
cwd = "."
timeout_seconds = 60
max_output_bytes = 65536
sensor = "junit_xml"
"""


def _setup_origin(
    tmp_path: Path, *, write_paths: str = '["src"]'
) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(
        ["git", "-C", str(origin), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(origin), "config", "core.autocrlf", "false"],
        check=True,
        capture_output=True,
        text=True,
    )
    (origin / "src").mkdir()
    (origin / "src" / "app.py").write_bytes(_WRONG_APP.encode("utf-8"))
    (origin / "notes.txt").write_bytes(_NOTES_BASE.encode("utf-8"))
    (origin / "verify_junit.py").write_bytes(_VERIFY_SCRIPT.encode("utf-8"))
    reports = origin / "reports"
    reports.mkdir()
    (reports / "junit.xml").write_bytes(_PLANTED_JUNIT.encode("utf-8"))
    _commit(origin, "base")
    config_path = tmp_path / "guardedcoder" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(_legal_toml(write_paths=write_paths), encoding="utf-8")
    return origin, config_path, tmp_path / "harness"


def _envelope_hash(config_path: Path) -> str:
    return synthesize_envelope(load_app_config(config_path)).envelope_hash


def _run(
    argv: list[str],
    *,
    config_path: Path,
    harness: Path,
    llm: object | None = None,
) -> int:
    return main(
        argv,
        llm=llm,
        config_path=config_path,
        harness_dir=harness,
        getpass_fn=lambda _prompt: "",
    )


def _db(harness: Path) -> sqlite3.Connection:
    return connect(harness / "guardedcoder.db")


def _modify_diff(path: str, old: str, new: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,1 @@\n"
        f"-{old.rstrip()}\n"
        f"+{new.rstrip()}\n"
    )


def _notes_diff() -> str:
    return _modify_diff("notes.txt", _NOTES_BASE, _NOTES_HITL)


def _app_diff() -> str:
    return _modify_diff("src/app.py", _WRONG_APP, _FIXED_APP)


def _lifecycle_llm() -> CaptureLLM:
    return CaptureLLM(
        MockLLM(
            responses=[
                json.dumps({"action": "apply_patch", "diff": _notes_diff()}),
                json.dumps({"action": "finish", "outcome": "success"}),
                json.dumps({"action": "apply_patch", "diff": _app_diff()}),
                json.dumps({"action": "finish", "outcome": "success"}),
            ],
            gate_on_fail=True,
        )
    )


def _run_argv(origin: Path, digest: str) -> list[str]:
    return [
        "run",
        "--repo",
        str(origin),
        "--task",
        "fix FLAG via HITL then FAIL gate",
        "--confirm-envelope-hash",
        digest,
    ]


def _pause_hitl(
    tmp_path: Path, *, write_paths: str = '["src"]'
) -> tuple[Path, Path, Path, CaptureLLM, str, str, Path]:
    origin, config_path, harness = _setup_origin(tmp_path, write_paths=write_paths)
    digest = _envelope_hash(config_path)
    llm = _lifecycle_llm()
    code = _run(
        _run_argv(origin, digest),
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    assert code == 0
    conn = _db(harness)
    row = conn.execute(
        "SELECT task_id, run_state, worktree_identity FROM tasks"
    ).fetchone()
    assert row is not None
    task_id, run_state, worktree = str(row[0]), str(row[1]), Path(str(row[2]))
    assert run_state == "awaiting_approval"
    fingerprint = str(
        conn.execute(
            "SELECT fingerprint FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    conn.close()
    return origin, config_path, harness, llm, task_id, fingerprint, worktree


def _mark(data: bytes) -> dict[str, object]:
    return {"exists": True, "sha256": hashlib.sha256(data).hexdigest()}


def _open_crash_window(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    action_kind: str,
    preimage: dict[str, dict[str, object]] | None = None,
    postimage: dict[str, dict[str, object]] | None = None,
    execution_started: int = 1,
) -> str:
    task = conn.execute(
        "SELECT envelope_hash, state_revision FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    pending = conn.execute(
        "SELECT pending_action_id, fingerprint, consumed FROM pending_actions "
        "WHERE task_id = ? ORDER BY rowid DESC",
        (task_id,),
    ).fetchone()
    assert task is not None and pending is not None
    assert int(pending[2]) == 1
    permit_id = create_permit(
        conn,
        task_id=task_id,
        action_id="e2e-crash",
        fingerprint=str(pending[1]),
        envelope_hash=str(task[0]),
        expected_revision=int(task[1]),
        pending_action_id=str(pending[0]),
    )
    window_id = consume_permit_and_open_window(
        conn,
        task_id=task_id,
        permit_id=permit_id,
        expected_revision=int(task[1]) + 1,
        action_kind=action_kind,
        preimage=preimage,
        postimage=postimage,
    )
    conn.execute(
        "UPDATE execution_windows SET execution_started = ? WHERE window_id = ?",
        (execution_started, window_id),
    )
    conn.commit()
    return window_id


def _approve_closed(
    *,
    config_path: Path,
    harness: Path,
    task_id: str,
    fingerprint: str,
) -> None:
    conn = _db(harness)
    conn.close()
    assert (
        _run(
            ["approve", task_id, fingerprint],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        == 0
    )


def test_offline_e2e_lifecycle_hitl_fail_gate_and_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, llm, task_id, hitl_fp, worktree = _pause_hitl(
        tmp_path
    )
    capsys.readouterr()
    assert worktree.is_dir()
    assert worktree.resolve() != origin.resolve()
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == _NOTES_BASE
    assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_BASE
    assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _WRONG_APP

    _approve_closed(
        config_path=config_path,
        harness=harness,
        task_id=task_id,
        fingerprint=hitl_fp,
    )
    capsys.readouterr()

    resumed = _run(
        ["resume", task_id, hitl_fp],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    capsys.readouterr()
    assert resumed == 0

    conn = _db(harness)
    row = conn.execute(
        "SELECT run_state, artifact_state FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "succeeded"
    assert row[1] == "patch_ready"
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == _NOTES_HITL
    assert (worktree / "src" / "app.py").read_text(encoding="utf-8") == _FIXED_APP
    assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_BASE
    assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _WRONG_APP

    fail_seen_at = None
    for index, call in enumerate(llm.calls):
        text = "\n".join(str(message.get("content", "")) for message in call)
        if (
            "FAIL" in text
            and "sensor" in text
            and "profile_id" in text
            and ("\"status\"" in text or "status" in text)
        ):
            fail_seen_at = index
            break
    assert fail_seen_at is not None
    assert fail_seen_at >= 1
    correction = json.loads(llm.responses[fail_seen_at])
    assert correction["action"] == "apply_patch"
    assert "src/app.py" in correction["diff"]
    assert "notes.txt" not in correction["diff"]

    fps = [
        str(item[0])
        for item in conn.execute(
            "SELECT fingerprint FROM permits WHERE task_id = ? ORDER BY rowid",
            (task_id,),
        )
    ]
    assert hitl_fp in fps
    assert any(fp != hitl_fp for fp in fps)

    junit_files = sorted((harness / "tasks" / task_id).glob("junit-*.xml"))
    assert len(junit_files) >= 2
    planted = (origin / "reports" / "junit.xml").resolve()
    for path in junit_files:
        assert path.resolve() != planted
        assert path.resolve().is_relative_to((harness / "tasks" / task_id).resolve())
        assert re.fullmatch(r"junit-[0-9a-f]{32}\.xml", path.name)
        assert "uuid" in str(path) or re.search(r"[0-9a-f]{32}", path.name)
    assert "{junit_out}" in config_path.read_text(encoding="utf-8")
    assert "junit_xml" in config_path.read_text(encoding="utf-8")

    service = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "guardedcoder"
        / "loop"
        / "service.py"
    )
    text = service.read_text(encoding="utf-8")
    assert "GitPatchArtifactPort" in text
    assert "StubPatchArtifactPort" not in text
    artifact = harness / "artifacts" / f"{task_id}.patch"
    assert artifact.is_file()
    body = artifact.read_bytes()
    assert b"src/app.py" in body
    assert b"notes.txt" in body

    status_before = _git(origin, "status", "--porcelain=v1", "--untracked-files=all")
    preview = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert preview == 0
    assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_BASE
    assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _WRONG_APP
    assert _git(origin, "status", "--porcelain=v1", "--untracked-files=all") == status_before

    confirmed = _run(
        ["apply", task_id, "--confirm"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert confirmed == 0
    assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_HITL
    assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _FIXED_APP
    assert (
        conn.execute(
            "SELECT artifact_state FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == "applied"
    )
    conn.close()


def test_evaluate_apply_patch_write_scope_and_fence(tmp_path: Path) -> None:
    origin, config_path, _harness = _setup_origin(tmp_path)
    envelope = synthesize_envelope(load_app_config(config_path))
    src = origin / "src"
    src.mkdir(exist_ok=True)
    (src / "app.py").write_text(_WRONG_APP, encoding="utf-8")
    (origin / "notes.txt").write_text(_NOTES_BASE, encoding="utf-8")
    budget = TaskBudget(remaining_steps=5)

    outside = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ApplyPatchAction(action="apply_patch", diff=_notes_diff()),
        budget=budget,
    )
    assert outside.kind == VerdictKind.NeedApproval

    inside = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ApplyPatchAction(action="apply_patch", diff=_app_diff()),
        budget=budget,
    )
    assert inside.kind == VerdictKind.Allow

    escape = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ApplyPatchAction(
            action="apply_patch",
            diff=_modify_diff("../secret.txt", "a", "b"),
        ),
        budget=budget,
    )
    assert escape.kind == VerdictKind.Deny
    assert escape.code == "WORKSPACE_ESCAPE"

    sensitive = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ApplyPatchAction(
            action="apply_patch",
            diff=_modify_diff(".env", "a", "b"),
        ),
        budget=budget,
    )
    assert sensitive.kind == VerdictKind.Deny
    assert sensitive.code == "SENSITIVE_PATH"

    listed = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ListDirAction(action="list_dir", path="notes.txt"),
        budget=budget,
    )
    assert listed.kind == VerdictKind.Deny
    read = evaluate(
        worktree=origin,
        envelope=envelope,
        action=ReadFileAction(action="read_file", path="notes.txt"),
        budget=budget,
    )
    assert read.kind == VerdictKind.Deny


@pytest.mark.parametrize(
    ("mode", "decision", "run_state"),
    [
        ("post", RecoverDecision.recorded_success, "running"),
        ("pre", RecoverDecision.retryable_same_attempt, "executing_action"),
        ("mixed", RecoverDecision.recorded_error, "error"),
    ],
)
def test_apply_patch_crash_recover_uses_real_task_worktree(
    tmp_path: Path,
    mode: str,
    decision: RecoverDecision,
    run_state: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, _llm, task_id, hitl_fp, worktree = _pause_hitl(
        tmp_path
    )
    capsys.readouterr()
    _approve_closed(
        config_path=config_path,
        harness=harness,
        task_id=task_id,
        fingerprint=hitl_fp,
    )
    notes_pre = _NOTES_BASE.encode("utf-8")
    app_pre = _WRONG_APP.encode("utf-8")
    notes_post = _NOTES_HITL.encode("utf-8")
    app_post = _FIXED_APP.encode("utf-8")
    preimage = {"notes.txt": _mark(notes_pre), "src/app.py": _mark(app_pre)}
    postimage = {"notes.txt": _mark(notes_post), "src/app.py": _mark(app_post)}
    if mode == "post":
        (worktree / "notes.txt").write_bytes(notes_post)
        (worktree / "src" / "app.py").write_bytes(app_post)
    elif mode == "pre":
        (worktree / "notes.txt").write_bytes(notes_pre)
        (worktree / "src" / "app.py").write_bytes(app_pre)
    else:
        (worktree / "notes.txt").write_bytes(notes_post)
        (worktree / "src" / "app.py").write_bytes(app_pre)

    conn = _db(harness)
    window_id = _open_crash_window(
        conn,
        task_id=task_id,
        action_kind="apply_patch",
        preimage=preimage,
        postimage=postimage,
    )
    revision = int(
        conn.execute(
            "SELECT state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    got = recover(
        conn, task_id=task_id, workspace=worktree, expected_revision=revision
    )
    assert got == decision
    assert (
        conn.execute(
            "SELECT run_state FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == run_state
    )
    if mode == "pre":
        assert (
            conn.execute(
                "SELECT status FROM execution_windows WHERE window_id = ?",
                (window_id,),
            ).fetchone()[0]
            == "executing_action"
        )
    conn.close()
    assert origin.is_dir()


def test_run_command_started_resume_does_not_call_spy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, _llm, task_id, hitl_fp, worktree = _pause_hitl(
        tmp_path
    )
    capsys.readouterr()
    _approve_closed(
        config_path=config_path,
        harness=harness,
        task_id=task_id,
        fingerprint=hitl_fp,
    )
    conn = _db(harness)
    _open_crash_window(
        conn,
        task_id=task_id,
        action_kind="run_command",
        execution_started=1,
    )
    conn.close()

    calls: list[object] = []

    def _spy(*_args: object, **_kwargs: object) -> None:
        calls.append(1)
        raise AssertionError("run_command must not rerun")

    monkeypatch.setattr("guardedcoder.tools.run_command.run_command", _spy)
    monkeypatch.setattr("guardedcoder.tools.executor.run_command", _spy)
    code = _run(
        ["resume", task_id, hitl_fp],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert code != 0
    assert calls == []
    conn = _db(harness)
    assert (
        conn.execute(
            "SELECT run_state FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == "error"
    )
    conn.close()
    assert worktree.is_dir()
    assert origin.is_dir()


def _two_file_ready(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    origin, config_path, harness = _setup_origin(tmp_path, write_paths='["."]')
    digest = _envelope_hash(config_path)
    diff = _notes_diff() + _app_diff()
    llm = MockLLM(
        responses=[
            json.dumps({"action": "apply_patch", "diff": diff}),
            json.dumps({"action": "finish", "outcome": "success"}),
        ]
    )
    assert (
        _run(
            _run_argv(origin, digest),
            config_path=config_path,
            harness=harness,
            llm=llm,
        )
        == 0
    )
    conn = _db(harness)
    row = conn.execute(
        "SELECT task_id, run_state, artifact_state, state_revision, "
        "worktree_identity, base_commit FROM tasks"
    ).fetchone()
    assert row is not None
    task_id = str(row[0])
    assert row[1] == "succeeded"
    assert row[2] == "patch_ready"
    port = GitPatchArtifactPort(artifact_dir=harness / "artifacts")
    artifact = port.export(
        SimpleNamespace(
            task_id=task_id,
            worktree_identity=str(row[4]),
            base_commit=str(row[5]),
            max_patch_bytes=1_000_000,
        )
    )
    preview = preview_apply(
        conn, task_id=task_id, expected_revision=int(row[3]), artifact=artifact
    )
    enter_applying(conn, preview)
    conn.close()
    return origin, config_path, harness, task_id


@pytest.mark.parametrize(
    ("mode", "origin_notes", "origin_app", "expect_applied", "token"),
    [
        ("post", _NOTES_HITL, _FIXED_APP, True, "applied"),
        ("pre", _NOTES_BASE, _WRONG_APP, False, "needs_reconfirm"),
        ("mixed", _NOTES_HITL, _WRONG_APP, False, "cleanup_error"),
    ],
)
def test_apply_back_applying_recover_from_real_succeeded_task(
    tmp_path: Path,
    mode: str,
    origin_notes: str,
    origin_app: str,
    expect_applied: bool,
    token: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, task_id = _two_file_ready(tmp_path)
    capsys.readouterr()
    (origin / "notes.txt").write_bytes(origin_notes.encode("utf-8"))
    (origin / "src" / "app.py").write_bytes(origin_app.encode("utf-8"))
    code = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    captured = capsys.readouterr()
    blob = (captured.out + captured.err).lower()
    if expect_applied:
        assert code == 0
    else:
        assert code != 0
    assert token in blob
    conn = _db(harness)
    state = str(
        conn.execute(
            "SELECT artifact_state FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    conn.close()
    if mode == "post":
        assert state == "applied"
        assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_HITL
        assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _FIXED_APP
    elif mode == "pre":
        assert state == "patch_ready"
        assert (origin / "notes.txt").read_text(encoding="utf-8") == _NOTES_BASE
    else:
        assert state == "cleanup_error"
        assert (origin / "src" / "app.py").read_text(encoding="utf-8") == _WRONG_APP


def test_stale_approval_permit_and_claim_are_not_replayable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, _llm, task_id, hitl_fp, worktree = _pause_hitl(
        tmp_path
    )
    capsys.readouterr()
    notes_before = (worktree / "notes.txt").read_bytes()
    _approve_closed(
        config_path=config_path,
        harness=harness,
        task_id=task_id,
        fingerprint=hitl_fp,
    )
    replay_approve = _run(
        ["approve", task_id, hitl_fp],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert replay_approve != 0
    assert (worktree / "notes.txt").read_bytes() == notes_before

    conn = _db(harness)
    with pytest.raises(PendingConsumedError):
        from guardedcoder.persist.approval import approve as persist_approve

        persist_approve(conn, task_id, hitl_fp)

    notes_pre = _NOTES_BASE.encode("utf-8")
    notes_post = _NOTES_HITL.encode("utf-8")
    window_id = _open_crash_window(
        conn,
        task_id=task_id,
        action_kind="apply_patch",
        preimage={"notes.txt": _mark(notes_pre)},
        postimage={"notes.txt": _mark(notes_post)},
        execution_started=1,
    )
    (worktree / "notes.txt").write_bytes(notes_pre)
    permit_id = str(
        conn.execute(
            "SELECT permit_id FROM execution_windows WHERE window_id = ?",
            (window_id,),
        ).fetchone()[0]
    )
    revision = int(
        conn.execute(
            "SELECT state_revision FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    with pytest.raises(PermitConsumedError):
        consume_permit_and_open_window(
            conn,
            task_id=task_id,
            permit_id=permit_id,
            expected_revision=revision,
            action_kind="apply_patch",
            preimage={"notes.txt": _mark(notes_pre)},
            postimage={"notes.txt": _mark(notes_post)},
        )
    windows = conn.execute(
        "SELECT COUNT(*) FROM execution_windows WHERE task_id = ?",
        (task_id,),
    ).fetchone()[0]
    assert windows == 1
    assert (worktree / "notes.txt").read_bytes() == notes_pre

    first_claim = claim_recovered_attempt(
        conn,
        task_id=task_id,
        window_id=window_id,
        expected_revision=revision,
        attempt_id="attempt-1",
    )
    with pytest.raises(ClaimConflictError):
        claim_recovered_attempt(
            conn,
            task_id=task_id,
            window_id=window_id,
            expected_revision=revision,
            attempt_id="attempt-2",
        )
    consumed = conn.execute(
        "SELECT consumed FROM recovered_attempt_claims WHERE claim_id = ?",
        (first_claim,),
    ).fetchone()[0]
    assert int(consumed) == 0
    assert (worktree / "notes.txt").read_bytes() == notes_pre
    conn.close()
    assert origin.is_dir()
