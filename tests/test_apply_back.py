from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from guardedcoder.persist.db import connect
from guardedcoder.persist.store import create_task
from guardedcoder.workspace.apply_back import (
    ApplyNotEligibleError,
    ApplyUnconfirmedError,
    confirm_apply,
    enter_applying,
    preview_apply,
    recover_apply,
)
from guardedcoder.workspace.artifact import GitPatchArtifactPort
from guardedcoder.workspace.gitops import assert_clean
from guardedcoder.workspace.worktree import create_task_worktree


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


def _setup(tmp_path: Path) -> tuple[sqlite3.Connection, Path, object, Path]:
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(
        ["git", "-C", str(origin), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    (origin / "tracked.txt").write_text("base\n", encoding="utf-8")
    (origin / "keep.txt").write_text("keep\n", encoding="utf-8")
    base = _commit(origin, "base")
    harness = tmp_path / "harness"
    ownership = create_task_worktree(
        task_id="task-33",
        repo_path=origin,
        base_commit=base,
        harness_dir=harness,
    )
    (ownership.worktree_path / "tracked.txt").write_text("patched\n", encoding="utf-8")
    task = type(
        "Task",
        (),
        {
            "task_id": "task-33",
            "worktree_identity": str(ownership.worktree_path),
            "base_commit": base,
            "max_patch_bytes": 1_000_000,
        },
    )()
    artifact = GitPatchArtifactPort(artifact_dir=tmp_path / "artifacts").export(task)
    conn = connect(tmp_path / "g.db")
    create_task(
        conn,
        task_id="task-33",
        run_state="succeeded",
        artifact_state="patch_ready",
        repo_path=str(origin.resolve()),
        base_commit=base,
        worktree_identity=str(ownership.worktree_path),
        envelope_hash="env-33",
        remaining_steps=3,
    )
    return conn, origin, artifact, ownership.worktree_path


def _task_row(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", ("task-33",)).fetchone()
    assert row is not None
    return row


@pytest.mark.parametrize(
    ("run_state", "artifact_state"),
    [
        ("running", "patch_ready"),
        ("succeeded", "worktree_present"),
        ("failed", "patch_ready"),
        ("succeeded", "applied"),
    ],
)
def test_apply_refuses_unless_succeeded_and_patch_ready(
    tmp_path: Path, run_state: str, artifact_state: str
) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    conn.execute(
        "UPDATE tasks SET run_state = ?, artifact_state = ? WHERE task_id = ?",
        (run_state, artifact_state, "task-33"),
    )
    conn.commit()
    before = (origin / "tracked.txt").read_text(encoding="utf-8")

    with pytest.raises(ApplyNotEligibleError):
        preview_apply(conn, task_id="task-33", expected_revision=1, artifact=artifact)

    assert (origin / "tracked.txt").read_text(encoding="utf-8") == before
    assert _task_row(conn)["artifact_state"] == artifact_state


def test_unconfirmed_apply_does_not_change_origin(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    origin_before = (origin / "tracked.txt").read_text(encoding="utf-8")
    status_before = _git(origin, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(ApplyUnconfirmedError):
        confirm_apply(conn, preview, confirmed=False)

    assert (origin / "tracked.txt").read_text(encoding="utf-8") == origin_before
    assert _git(origin, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert _task_row(conn)["artifact_state"] == "patch_ready"
    assert _task_row(conn)["run_state"] == "succeeded"
    assert _git(origin, "rev-parse", "HEAD") == preview.base_commit


def test_confirmed_apply_writes_origin_after_applying_window(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    assert preview.fingerprint == artifact.sha256
    assert artifact.sha256 in preview.summary
    assert_clean(origin)

    confirm_apply(conn, preview, confirmed=True)

    assert (origin / "tracked.txt").read_text(encoding="utf-8") == "patched\n"
    assert (origin / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    row = _task_row(conn)
    assert row["run_state"] == "succeeded"
    assert row["artifact_state"] == "applied"
    assert _git(origin, "log", "-1", "--pretty=%s") == "base"


def test_recover_all_postimage_marks_applied(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    (origin / "tracked.txt").write_text("patched\n", encoding="utf-8")

    decision = recover_apply(
        conn, task_id="task-33", expected_revision=2, origin=origin
    )

    assert decision == "applied"
    row = _task_row(conn)
    assert row["artifact_state"] == "applied"
    assert row["run_state"] == "succeeded"


def test_recover_all_preimage_requires_reconfirm(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    assert (origin / "tracked.txt").read_text(encoding="utf-8") == "base\n"

    decision = recover_apply(
        conn, task_id="task-33", expected_revision=2, origin=origin
    )

    assert decision == "needs_reconfirm"
    row = _task_row(conn)
    assert row["artifact_state"] == "patch_ready"
    assert row["run_state"] == "succeeded"
    assert (origin / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    preview2 = preview_apply(
        conn, task_id="task-33", expected_revision=row["state_revision"], artifact=artifact
    )
    with pytest.raises(ApplyUnconfirmedError):
        confirm_apply(conn, preview2, confirmed=False)


def test_recover_mixed_sets_cleanup_error(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    (origin / "tracked.txt").write_text("partial\n", encoding="utf-8")

    decision = recover_apply(
        conn, task_id="task-33", expected_revision=2, origin=origin
    )

    assert decision == "cleanup_error"
    row = _task_row(conn)
    assert row["artifact_state"] == "cleanup_error"
    assert row["run_state"] == "succeeded"
    assert (origin / "tracked.txt").read_text(encoding="utf-8") == "partial\n"


def test_preview_does_not_stage_or_commit_origin(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    status_before = _git(origin, "status", "--porcelain=v1")
    head = _git(origin, "rev-parse", "HEAD")
    preview_apply(conn, task_id="task-33", expected_revision=1, artifact=artifact)
    assert _git(origin, "status", "--porcelain=v1") == status_before
    assert _git(origin, "rev-parse", "HEAD") == head
    assert hashlib.sha256(artifact.body).hexdigest() == artifact.sha256


def test_recover_refuses_origin_that_is_not_the_task_repo(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "tracked.txt").write_text("patched\n", encoding="utf-8")

    with pytest.raises(ApplyNotEligibleError):
        recover_apply(
            conn, task_id="task-33", expected_revision=2, origin=decoy
        )

    row = _task_row(conn)
    assert row["artifact_state"] == "applying"
    assert (origin / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_recover_empty_postimage_is_cleanup_error(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    conn.execute(
        "UPDATE execution_windows SET postimage_json = ? WHERE task_id = ?",
        ("{}", "task-33"),
    )
    conn.commit()

    decision = recover_apply(
        conn, task_id="task-33", expected_revision=2, origin=origin
    )

    assert decision == "cleanup_error"
    assert _task_row(conn)["artifact_state"] == "cleanup_error"


def test_recover_rejects_escaped_image_paths(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    enter_applying(conn, preview)
    secret = tmp_path / "secret.txt"
    secret.write_text("leak\n", encoding="utf-8")
    digest = hashlib.sha256(b"leak\n").hexdigest()
    escaped = {
        "../secret.txt": {"exists": True, "sha256": digest},
    }
    conn.execute(
        "UPDATE execution_windows SET preimage_json = ?, postimage_json = ? "
        "WHERE task_id = ?",
        (json.dumps(escaped), json.dumps(escaped), "task-33"),
    )
    conn.commit()

    decision = recover_apply(
        conn, task_id="task-33", expected_revision=2, origin=origin
    )

    assert decision == "cleanup_error"
    assert secret.read_text(encoding="utf-8") == "leak\n"


def test_enter_applying_on_legacy_not_null_permit_schema(tmp_path: Path) -> None:
    conn, origin, artifact, _wt = _setup(tmp_path)
    preview = preview_apply(
        conn, task_id="task-33", expected_revision=1, artifact=artifact
    )
    legacy = tmp_path / "legacy.db"
    raw = sqlite3.connect(legacy)
    raw.executescript(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            run_state TEXT NOT NULL,
            artifact_state TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            base_commit TEXT NOT NULL,
            worktree_identity TEXT NOT NULL,
            envelope_hash TEXT NOT NULL,
            state_revision INTEGER NOT NULL,
            remaining_steps INTEGER NOT NULL
        );
        CREATE TABLE permits (
            permit_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            action_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            envelope_hash TEXT NOT NULL,
            state_revision INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0,
            pending_action_id TEXT
        );
        CREATE TABLE execution_windows (
            window_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            permit_id TEXT NOT NULL REFERENCES permits(permit_id),
            action_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            preimage_json TEXT,
            postimage_json TEXT,
            opened_revision INTEGER NOT NULL,
            source_run_state TEXT NOT NULL
        );
        """
    )
    raw.execute(
        "INSERT INTO tasks ("
        "task_id, run_state, artifact_state, repo_path, base_commit, "
        "worktree_identity, envelope_hash, state_revision, remaining_steps"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "task-33",
            "succeeded",
            "patch_ready",
            str(origin.resolve()),
            preview.base_commit,
            str(preview.worktree),
            "env-33",
            1,
            3,
        ),
    )
    raw.commit()
    raw.close()
    migrated = connect(legacy)
    enter_applying(migrated, preview)
    row = migrated.execute(
        "SELECT permit_id, status FROM execution_windows WHERE task_id = ?",
        ("task-33",),
    ).fetchone()
    assert row is not None
    assert row[1] == "applying"
