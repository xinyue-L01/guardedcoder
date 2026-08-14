from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from guardedcoder.cli import main, parse_args
from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.governance.evaluate import Verdict, VerdictKind
from guardedcoder.loop import engine as engine_mod
from guardedcoder.persist.db import connect


def _fake_key() -> str:
    return "sk" + "-test"


class BoomLLM:
    def complete(self, messages: list[dict[str, str]]) -> str:
        raise AssertionError("LLM.complete must not be called")


class RecordingLLM:
    def __init__(self, responses: list[str]) -> None:
        self._remaining = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self._remaining:
            raise AssertionError("unexpected extra LLM.complete")
        return self._remaining.pop(0)


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


def _legal_toml() -> str:
    return """\
config_schema_version = "1"
read_paths = ["src"]
write_paths = ["src"]
verify_profiles = ["ok"]
max_steps = 8
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
profile_id = "ok"
argv_template = ["python", "-c", "raise SystemExit(0)"]
cwd = "."
timeout_seconds = 60
max_output_bytes = 65536
sensor = "exit_code"
"""


def _setup_origin(tmp_path: Path) -> tuple[Path, Path, Path, str]:
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
    (origin / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    base = _commit(origin, "base")
    config_path = tmp_path / "guardedcoder" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(_legal_toml(), encoding="utf-8")
    harness = tmp_path / "harness"
    return origin, config_path, harness, base


def _envelope_hash(config_path: Path) -> str:
    return synthesize_envelope(load_app_config(config_path)).envelope_hash


def _run(
    argv: list[str],
    *,
    config_path: Path,
    harness: Path,
    llm: object | None = None,
    key_store: object | None = None,
) -> int:
    return main(
        argv,
        llm=llm,
        key_store=key_store,
        config_path=config_path,
        harness_dir=harness,
        getpass_fn=lambda _prompt: "",
    )


def _db(harness: Path) -> sqlite3.Connection:
    return connect(harness / "guardedcoder.db")


def _worktrees(origin: Path) -> list[str]:
    output = _git(origin, "worktree", "list", "--porcelain")
    return [line for line in output.splitlines() if line.startswith("worktree ")]


def _need_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    def _verdict(*_args: object, **_kwargs: object) -> Verdict:
        return Verdict(kind=VerdictKind.NeedApproval, code=None)

    monkeypatch.setattr(engine_mod, "evaluate", _verdict)


def test_run_parses_repo_task_and_confirm_hash() -> None:
    ns = parse_args(
        [
            "run",
            "--repo",
            "r",
            "--task",
            "do work",
            "--confirm-envelope-hash",
            "abc",
        ]
    )
    assert ns.command == "run"
    assert ns.repo == "r"
    assert ns.task == "do work"
    assert ns.confirm_envelope_hash == "abc"


def test_resume_requires_task_id_and_fingerprint() -> None:
    assert main(["resume"]) != 0
    assert main(["resume", "task-1"]) != 0
    ns = parse_args(["resume", "task-9", "deadbeef"])
    assert ns.task_id == "task-9"
    assert ns.fingerprint == "deadbeef"


def test_unconfirmed_run_shows_effective_envelope_and_skips_worktree_and_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    llm = BoomLLM()
    code = _run(
        ["run", "--repo", str(origin), "--task", "ship feature"],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "http://127.0.0.1:8080/v1" in out
    assert "task description" in out.lower() or "data types" in out.lower()
    assert "read_paths" in out
    assert "write_paths" in out
    assert "profiles" in out
    assert "verify_profiles" in out
    assert "max_steps" in out
    assert "allow_network" in out
    assert "allow_delete" in out
    assert _envelope_hash(config_path) in out
    assert len(_worktrees(origin)) == 1
    assert not (harness / "worktrees").exists()
    assert not (harness / "guardedcoder.db").exists()


def test_wrong_envelope_hash_skips_worktree_and_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    llm = BoomLLM()
    code = _run(
        [
            "run",
            "--repo",
            str(origin),
            "--task",
            "ship feature",
            "--confirm-envelope-hash",
            "0" * 64,
        ],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    capsys.readouterr()
    assert code != 0
    assert len(_worktrees(origin)) == 1
    assert not (harness / "worktrees").exists()
    assert not (harness / "guardedcoder.db").exists()


def test_dirty_origin_is_refused_without_worktree_or_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    (origin / "src" / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    llm = BoomLLM()
    digest = _envelope_hash(config_path)
    code = _run(
        [
            "run",
            "--repo",
            str(origin),
            "--task",
            "ship feature",
            "--confirm-envelope-hash",
            digest,
        ],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    capsys.readouterr()
    assert code != 0
    assert (origin / "src" / "dirty.py").read_text(encoding="utf-8") == "x = 1\n"
    assert _git(origin, "stash", "list") == ""
    assert len(_worktrees(origin)) == 1
    assert not (harness / "worktrees").exists()


def test_approve_and_reject_bind_fingerprint_and_refuse_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    llm = RecordingLLM(responses=['{"action":"list_dir","path":"src"}'])
    _need_approval(monkeypatch)
    code = _run(
        [
            "run",
            "--repo",
            str(origin),
            "--task",
            "needs hitl",
            "--confirm-envelope-hash",
            digest,
        ],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    capsys.readouterr()
    assert code == 0
    assert len(llm.calls) == 1
    conn = _db(harness)
    task_id = str(conn.execute("SELECT task_id FROM tasks").fetchone()[0])
    pending = conn.execute(
        "SELECT fingerprint, consumed FROM pending_actions WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert pending is not None
    fingerprint, consumed = str(pending[0]), int(pending[1])
    assert consumed == 0
    assert conn.execute("SELECT run_state FROM tasks").fetchone()[0] == "awaiting_approval"

    assert (
        _run(
            ["approve", task_id, "wrong-fingerprint"],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        != 0
    )
    assert (
        conn.execute(
            "SELECT consumed FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == 0
    )

    assert (
        _run(
            ["approve", task_id, fingerprint],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        == 0
    )
    assert (
        conn.execute(
            "SELECT consumed FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == 1
    )
    replay = _run(
        ["approve", task_id, fingerprint],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    assert replay != 0


def test_reject_binds_fingerprint_returns_running_and_refuses_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    llm = RecordingLLM(responses=['{"action":"list_dir","path":"src"}'])
    _need_approval(monkeypatch)
    assert (
        _run(
            [
                "run",
                "--repo",
                str(origin),
                "--task",
                "needs hitl",
                "--confirm-envelope-hash",
                digest,
            ],
            config_path=config_path,
            harness=harness,
            llm=llm,
        )
        == 0
    )
    capsys.readouterr()
    conn = _db(harness)
    task_id = str(conn.execute("SELECT task_id FROM tasks").fetchone()[0])
    fingerprint = str(
        conn.execute(
            "SELECT fingerprint FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )

    assert (
        _run(
            ["reject", task_id, "wrong-fingerprint"],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        != 0
    )
    assert conn.execute("SELECT run_state FROM tasks").fetchone()[0] == "awaiting_approval"
    assert (
        conn.execute(
            "SELECT consumed FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == 0
    )

    assert (
        _run(
            ["reject", task_id, fingerprint],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        == 0
    )
    assert conn.execute("SELECT run_state FROM tasks").fetchone()[0] == "running"
    assert (
        conn.execute(
            "SELECT consumed FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        _run(
            ["reject", task_id, fingerprint],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        != 0
    )


def test_resume_mismatch_fails_closed_to_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    origin, config_path, harness, _base = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    llm = RecordingLLM(responses=['{"action":"list_dir","path":"src"}'])
    _need_approval(monkeypatch)
    assert (
        _run(
            [
                "run",
                "--repo",
                str(origin),
                "--task",
                "needs hitl",
                "--confirm-envelope-hash",
                digest,
            ],
            config_path=config_path,
            harness=harness,
            llm=llm,
        )
        == 0
    )
    capsys.readouterr()
    conn = _db(harness)
    task_id = str(conn.execute("SELECT task_id FROM tasks").fetchone()[0])
    fingerprint = str(
        conn.execute(
            "SELECT fingerprint FROM pending_actions WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    assert (
        _run(
            ["approve", task_id, fingerprint],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        == 0
    )

    wrong = _run(
        ["resume", task_id, "mismatched-fingerprint"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    assert wrong != 0
    assert conn.execute("SELECT run_state FROM tasks").fetchone()[0] == "error"

    conn.execute(
        "UPDATE tasks SET run_state = ?, envelope_hash = ? WHERE task_id = ?",
        ("awaiting_approval", "deadbeef" * 8, task_id),
    )
    conn.commit()
    env_mismatch = _run(
        ["resume", task_id, fingerprint],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    assert env_mismatch != 0
    assert conn.execute("SELECT run_state FROM tasks").fetchone()[0] == "error"
    assert len(llm.calls) == 1
