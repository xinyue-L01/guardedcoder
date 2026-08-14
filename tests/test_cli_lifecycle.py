from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from guardedcoder.auth.keyring_store import KeyringStore
from guardedcoder.cli import main, parse_args
from guardedcoder.config.load import load_app_config
from guardedcoder.config.synthesize import synthesize_envelope
from guardedcoder.llm.mock import MockLLM
from guardedcoder.persist.db import connect
from guardedcoder.workspace.artifact import GitPatchArtifactPort


def _fake_secret() -> str:
    return "sk" + "-test_AbCdEf0123456789"


class BoomLLM:
    def complete(self, messages: list[dict[str, str]]) -> str:
        raise AssertionError("LLM.complete must not be called")


class FakeKeyring:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        del self.data[(service, username)]


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
    exe = sys.executable.replace("\\", "/")
    return f"""\
config_schema_version = "1"
read_paths = ["."]
write_paths = ["."]
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
argv_template = ["{exe}", "-c", "raise SystemExit(0)"]
cwd = "."
timeout_seconds = 60
max_output_bytes = 65536
sensor = "exit_code"
"""


def _setup_origin(tmp_path: Path) -> tuple[Path, Path, Path]:
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
    (origin / "tracked.txt").write_bytes(b"base\n")
    (origin / "keep.txt").write_bytes(b"keep\n")
    _commit(origin, "base")
    config_path = tmp_path / "guardedcoder" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(_legal_toml(), encoding="utf-8")
    return origin, config_path, tmp_path / "harness"


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


def _patch_diff() -> str:
    return (
        "--- a/tracked.txt\n"
        "+++ b/tracked.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-base\n"
        "+patched\n"
    )


def _finish_llm() -> MockLLM:
    return MockLLM(
        responses=[
            json.dumps({"action": "apply_patch", "diff": _patch_diff()}),
            json.dumps({"action": "finish", "outcome": "success"}),
        ]
    )


def test_apply_and_discard_parse_task_id_only() -> None:
    apply_ns = parse_args(["apply", "task-1"])
    assert apply_ns.command == "apply"
    assert apply_ns.task_id == "task-1"
    assert apply_ns.confirm is False
    discard_ns = parse_args(["discard", "task-2"])
    assert discard_ns.command == "discard"
    assert discard_ns.task_id == "task-2"
    assert not hasattr(discard_ns, "path") or getattr(discard_ns, "path", None) is None


def test_apply_preview_does_not_mutate_origin_confirm_then_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    llm = _finish_llm()
    code = _run(
        [
            "run",
            "--repo",
            str(origin),
            "--task",
            "patch tracked file",
            "--confirm-envelope-hash",
            digest,
        ],
        config_path=config_path,
        harness=harness,
        llm=llm,
    )
    capsys.readouterr()
    assert code == 0
    conn = _db(harness)
    row = conn.execute(
        "SELECT task_id, run_state, artifact_state FROM tasks"
    ).fetchone()
    assert row is not None
    task_id, run_state, artifact_state = str(row[0]), str(row[1]), str(row[2])
    assert run_state == "succeeded"
    assert artifact_state == "patch_ready"
    assert (origin / "tracked.txt").read_bytes() == b"base\n"
    status_before = _git(origin, "status", "--porcelain=v1", "--untracked-files=all")

    preview = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    out = capsys.readouterr().out
    assert preview == 0
    assert (origin / "tracked.txt").read_bytes() == b"base\n"
    assert _git(origin, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert "sha256=" in out or "fingerprint" in out.lower()

    confirmed = _run(
        ["apply", task_id, "--confirm"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert confirmed == 0
    assert (origin / "tracked.txt").read_bytes() == b"patched\n"
    assert (origin / "keep.txt").read_bytes() == b"keep\n"
    assert (
        conn.execute(
            "SELECT artifact_state FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        == "applied"
    )


def test_product_finish_uses_git_patch_artifact_port(tmp_path: Path) -> None:
    origin, config_path, harness = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    code = _run(
        [
            "run",
            "--repo",
            str(origin),
            "--task",
            "patch tracked file",
            "--confirm-envelope-hash",
            digest,
        ],
        config_path=config_path,
        harness=harness,
        llm=_finish_llm(),
    )
    assert code == 0
    conn = _db(harness)
    task_id = str(conn.execute("SELECT task_id FROM tasks").fetchone()[0])
    artifact = harness / "artifacts" / f"{task_id}.patch"
    assert artifact.is_file()
    body = artifact.read_bytes()
    assert b"tracked.txt" in body
    assert GitPatchArtifactPort.__name__ == "GitPatchArtifactPort"
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


def test_discard_takes_only_task_id_and_rejects_path_arg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness = _setup_origin(tmp_path)
    digest = _envelope_hash(config_path)
    assert (
        _run(
            [
                "run",
                "--repo",
                str(origin),
                "--task",
                "patch tracked file",
                "--confirm-envelope-hash",
                digest,
            ],
            config_path=config_path,
            harness=harness,
            llm=_finish_llm(),
        )
        == 0
    )
    capsys.readouterr()
    conn = _db(harness)
    task_id = str(conn.execute("SELECT task_id FROM tasks").fetchone()[0])
    worktree = Path(
        conn.execute(
            "SELECT worktree_identity FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    )
    assert worktree.is_dir()

    with_path = _run(
        ["discard", task_id, str(worktree)],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    capsys.readouterr()
    assert with_path != 0
    assert worktree.is_dir()

    assert (
        _run(
            ["discard", task_id],
            config_path=config_path,
            harness=harness,
            llm=BoomLLM(),
        )
        == 0
    )
    capsys.readouterr()
    assert not worktree.exists()
    row = conn.execute(
        "SELECT run_state, artifact_state FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert row[0] == "succeeded"
    assert row[1] == "discarded"


def test_memory_clear_requires_repo_id_and_secret_write_is_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness = _setup_origin(tmp_path)
    store = KeyringStore(backend=FakeKeyring())
    secret = _fake_secret()

    assert main(["memory", "clear"]) != 0
    ns = parse_args(["memory", "clear", "--repo-id", "repo-a"])
    assert ns.memory_command == "clear"
    assert ns.repo_id == "repo-a"

    added = _run(
        [
            "memory",
            "add",
            "--repo-id",
            "repo-a",
            "--type",
            "project_constraint",
            "--content",
            "Use pytest.",
        ],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    capsys.readouterr()
    assert added == 0
    conn = _db(harness)
    assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1

    refused = _run(
        [
            "memory",
            "add",
            "--repo-id",
            "repo-a",
            "--type",
            "constraint",
            "--content",
            "Never store " + secret,
        ],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    captured = capsys.readouterr()
    assert refused != 0
    assert secret not in captured.out
    assert secret not in captured.err
    assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1

    summary = _run(
        [
            "memory",
            "add",
            "--repo-id",
            "repo-a",
            "--type",
            "task_summary",
            "--content",
            "harness only",
        ],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    capsys.readouterr()
    assert summary != 0
    assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1

    listed = _run(
        ["memory", "list", "--repo-id", "repo-a"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    listed_out = capsys.readouterr().out
    assert listed == 0
    assert "Use pytest." in listed_out

    exported = _run(
        ["memory", "export", "--repo-id", "repo-a"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    export_out = capsys.readouterr().out
    assert exported == 0
    payload = json.loads(export_out)
    assert payload["repo_id"] == "repo-a"
    assert payload["records"][0]["content"] == "Use pytest."

    cleared = _run(
        ["memory", "clear", "--repo-id", "repo-a"],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
        key_store=store,
    )
    capsys.readouterr()
    assert cleared == 0
    assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 0
    assert origin.is_dir()


def test_memory_type_accepts_constraint_alias(tmp_path: Path) -> None:
    origin, config_path, harness = _setup_origin(tmp_path)
    ns = parse_args(
        [
            "memory",
            "add",
            "--repo-id",
            "repo-a",
            "--type",
            "project_constraint",
            "--content",
            "Use pytest.",
        ]
    )
    assert ns.type == "project_constraint"
    code = _run(
        [
            "memory",
            "add",
            "--repo-id",
            "repo-a",
            "--type",
            "constraint",
            "--content",
            "Alias still works.",
        ],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    assert code == 0
    conn = _db(harness)
    types = {
        str(row[0])
        for row in conn.execute("SELECT record_type FROM memory_records")
    }
    assert "project_constraint" in types
    del origin


def _seed_applying(
    tmp_path: Path, *, origin_body: bytes
) -> tuple[Path, Path, Path, str]:
    from guardedcoder.persist.store import create_task
    from guardedcoder.workspace.apply_back import enter_applying, preview_apply
    from guardedcoder.workspace.worktree import create_task_worktree

    origin, config_path, harness = _setup_origin(tmp_path)
    base = _git(origin, "rev-parse", "HEAD")
    ownership = create_task_worktree(
        task_id="task-apply",
        repo_path=origin,
        base_commit=base,
        harness_dir=harness,
    )
    (ownership.worktree_path / "tracked.txt").write_bytes(b"patched\n")
    conn = connect(harness / "guardedcoder.db")
    create_task(
        conn,
        task_id="task-apply",
        run_state="succeeded",
        artifact_state="patch_ready",
        repo_path=str(origin.resolve()),
        base_commit=base,
        worktree_identity=str(ownership.worktree_path),
        envelope_hash="env-apply",
        remaining_steps=3,
    )
    artifact = GitPatchArtifactPort(artifact_dir=harness / "artifacts").export(
        type(
            "Task",
            (),
            {
                "task_id": "task-apply",
                "worktree_identity": str(ownership.worktree_path),
                "base_commit": base,
                "max_patch_bytes": 1_000_000,
            },
        )()
    )
    preview = preview_apply(
        conn, task_id="task-apply", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    (origin / "tracked.txt").write_bytes(origin_body)
    return origin, config_path, harness, "task-apply"


def test_apply_recover_applied_is_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, task_id = _seed_applying(
        tmp_path, origin_body=b"patched\n"
    )
    code = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    out = capsys.readouterr().out.lower()
    assert code == 0
    assert "applied" in out
    assert "needs_reconfirm" not in out
    assert (origin / "tracked.txt").read_bytes() == b"patched\n"


def test_apply_recover_needs_reconfirm_is_not_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, task_id = _seed_applying(
        tmp_path, origin_body=b"base\n"
    )
    code = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    captured = capsys.readouterr()
    blob = (captured.out + captured.err).lower()
    assert code != 0
    assert "applied" not in blob.split("needs_reconfirm")[0] or "needs_reconfirm" in blob
    assert "needs_reconfirm" in blob
    assert (origin / "tracked.txt").read_bytes() == b"base\n"


def test_apply_recover_cleanup_error_is_nonzero_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, config_path, harness, task_id = _seed_applying(
        tmp_path, origin_body=b"partial\n"
    )
    code = _run(
        ["apply", task_id],
        config_path=config_path,
        harness=harness,
        llm=BoomLLM(),
    )
    captured = capsys.readouterr()
    blob = (captured.out + captured.err).lower()
    assert code != 0
    assert "cleanup_error" in blob or "partial" in blob
    assert "origin" in blob
    assert (origin / "tracked.txt").read_bytes() == b"partial\n"
