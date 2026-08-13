from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from guardedcoder.errors import ExecutionWindowOpenError, StaleRevisionError
from guardedcoder.persist.txn import write_txn
from guardedcoder.workspace.artifact import PatchArtifact
from guardedcoder.workspace.gitops import GitOperationError, assert_clean, git_text


class ApplyBackError(RuntimeError):
    """Raised when apply-back preview, confirm, or recover fails closed."""


class ApplyNotEligibleError(ApplyBackError):
    """Raised when apply is requested outside succeeded+patch_ready."""


class ApplyUnconfirmedError(ApplyBackError):
    """Raised when apply is not explicitly confirmed; origin stays unchanged."""


class ApplyRecoverDecision(StrEnum):
    applied = "applied"
    needs_reconfirm = "needs_reconfirm"
    cleanup_error = "cleanup_error"


@dataclass(frozen=True)
class ApplyPreview:
    task_id: str
    expected_revision: int
    fingerprint: str
    summary: str
    origin: Path
    artifact_path: Path
    worktree: Path
    base_commit: str
    preimage: dict[str, dict[str, object]]
    postimage: dict[str, dict[str, object]]


def preview_apply(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    expected_revision: int,
    artifact: PatchArtifact,
) -> ApplyPreview:
    task = _load_task(conn, task_id)
    _require_eligible(task, expected_revision)
    origin = Path(task["repo_path"]).expanduser().resolve()
    worktree = Path(task["worktree_identity"]).expanduser().resolve()
    base_commit = str(task["base_commit"])
    assert_clean(origin)
    head = git_text(origin, "rev-parse", "HEAD").lower()
    if head != base_commit.lower():
        raise ApplyNotEligibleError("origin base commit has changed")
    _git_apply(origin, artifact.path, check=True)
    paths = _patch_paths(artifact.body)
    preimage = {rel: _required_mark(origin, rel) for rel in paths}
    postimage = {rel: _required_mark(worktree, rel) for rel in paths}
    return ApplyPreview(
        task_id=task_id,
        expected_revision=expected_revision,
        fingerprint=artifact.sha256,
        summary=artifact.summary(max_bytes=4_096),
        origin=origin,
        artifact_path=artifact.path,
        worktree=worktree,
        base_commit=base_commit,
        preimage=preimage,
        postimage=postimage,
    )


def confirm_apply(
    conn: sqlite3.Connection,
    preview: ApplyPreview,
    *,
    confirmed: bool,
) -> None:
    if not confirmed:
        raise ApplyUnconfirmedError("apply requires explicit confirmation")
    enter_applying(conn, preview)
    try:
        _git_apply(preview.origin, preview.artifact_path, check=False)
    except GitOperationError:
        recover_apply(
            conn,
            task_id=preview.task_id,
            expected_revision=preview.expected_revision + 1,
            origin=preview.origin,
        )
        raise
    _finish_applied(conn, preview)


def enter_applying(conn: sqlite3.Connection, preview: ApplyPreview) -> str:
    """Persist fingerprint, images, and applying before any origin mutation."""
    window_id = str(uuid.uuid4())
    conn.row_factory = sqlite3.Row
    with write_txn(conn):
        task = _load_task(conn, preview.task_id)
        _require_eligible(task, preview.expected_revision)
        assert_clean(preview.origin)
        head = git_text(preview.origin, "rev-parse", "HEAD").lower()
        if head != preview.base_commit.lower():
            raise ApplyNotEligibleError("origin base commit has changed")
        if _active_lifecycle_window(conn, preview.task_id):
            raise ExecutionWindowOpenError(
                f"task {preview.task_id} already has an active execution window"
            )
        new_revision = preview.expected_revision + 1
        conn.execute(
            "INSERT INTO execution_windows ("
            "window_id, task_id, permit_id, action_kind, status, "
            "preimage_json, postimage_json, opened_revision, source_run_state, "
            "fingerprint) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                window_id,
                preview.task_id,
                "apply_back",
                "applying",
                json.dumps(preview.preimage, ensure_ascii=False),
                json.dumps(preview.postimage, ensure_ascii=False),
                new_revision,
                "succeeded",
                preview.fingerprint,
            ),
        )
        cur = conn.execute(
            "UPDATE tasks SET artifact_state = ?, state_revision = ? "
            "WHERE task_id = ? AND state_revision = ? AND run_state = ?",
            (
                "applying",
                new_revision,
                preview.task_id,
                preview.expected_revision,
                "succeeded",
            ),
        )
        if cur.rowcount != 1:
            raise StaleRevisionError(
                f"stale revision for task {preview.task_id}: "
                f"expected {preview.expected_revision}"
            )
    return window_id


def recover_apply(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    expected_revision: int,
    origin: Path,
) -> ApplyRecoverDecision:
    origin = Path(origin).expanduser().resolve()
    conn.row_factory = sqlite3.Row
    with write_txn(conn):
        win = conn.execute(
            "SELECT * FROM execution_windows WHERE task_id = ? "
            "AND status = ? ORDER BY rowid DESC",
            (task_id, "applying"),
        ).fetchone()
        if win is None:
            raise ApplyNotEligibleError(f"no applying window for task {task_id}")
        task = _load_task(conn, task_id)
        if task["state_revision"] != expected_revision:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        if task["artifact_state"] != "applying" or task["run_state"] != "succeeded":
            raise ApplyNotEligibleError("apply recovery requires succeeded+applying")
        owned = Path(task["repo_path"]).expanduser().resolve()
        if origin != owned:
            raise ApplyNotEligibleError("origin path does not match task repository")
        try:
            preimage = json.loads(win["preimage_json"] or "")
            postimage = json.loads(win["postimage_json"] or "")
        except (TypeError, json.JSONDecodeError, ValueError):
            preimage, postimage = None, None
        decision = ApplyRecoverDecision.cleanup_error
        artifact_state = "cleanup_error"
        window_status = "cleanup_error"
        if (
            isinstance(preimage, dict)
            and isinstance(postimage, dict)
            and preimage
            and postimage
            and set(preimage) == set(postimage)
        ):
            match_post = _matches_image(origin, postimage)
            match_pre = _matches_image(origin, preimage)
            if match_post:
                decision = ApplyRecoverDecision.applied
                artifact_state = "applied"
                window_status = "applied"
            elif match_pre:
                decision = ApplyRecoverDecision.needs_reconfirm
                artifact_state = "patch_ready"
                window_status = "needs_reconfirm"
        new_revision = expected_revision + 1
        cur = conn.execute(
            "UPDATE tasks SET artifact_state = ?, state_revision = ? "
            "WHERE task_id = ? AND state_revision = ? AND run_state = ?",
            (artifact_state, new_revision, task_id, expected_revision, "succeeded"),
        )
        if cur.rowcount != 1:
            raise StaleRevisionError(
                f"stale revision for task {task_id}: expected {expected_revision}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE window_id = ?",
            (window_status, win["window_id"]),
        )
        return decision


def _finish_applied(conn: sqlite3.Connection, preview: ApplyPreview) -> None:
    expected = preview.expected_revision + 1
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET artifact_state = ?, state_revision = state_revision + 1 "
            "WHERE task_id = ? AND state_revision = ? AND run_state = ? "
            "AND artifact_state = ?",
            ("applied", preview.task_id, expected, "succeeded", "applying"),
        )
        if cur.rowcount != 1:
            raise StaleRevisionError(
                f"stale revision for task {preview.task_id}: expected {expected}"
            )
        conn.execute(
            "UPDATE execution_windows SET status = ? WHERE task_id = ? AND status = ?",
            ("applied", preview.task_id, "applying"),
        )


def _load_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        raise ApplyNotEligibleError(f"task {task_id} not found")
    return row


def _require_eligible(task: sqlite3.Row, expected_revision: int) -> None:
    if task["state_revision"] != expected_revision:
        raise StaleRevisionError(
            f"stale revision for task {task['task_id']}: expected {expected_revision}"
        )
    if task["run_state"] != "succeeded" or task["artifact_state"] != "patch_ready":
        raise ApplyNotEligibleError("apply requires succeeded and patch_ready")


def _active_lifecycle_window(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM execution_windows WHERE task_id = ? "
        "AND status IN ('executing_action', 'applying')",
        (task_id,),
    ).fetchone()
    return row is not None


def _git_apply(origin: Path, patch: Path, *, check: bool) -> None:
    args = ["apply", "--whitespace=nowarn"]
    if check:
        args.append("--check")
    args.extend(["--", str(patch)])
    git_text(origin, *args)


def _patch_paths(body: bytes) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in body.splitlines():
        if not raw.startswith(b"diff --git "):
            continue
        text = raw.decode("utf-8", errors="replace")
        parts = text.split()
        if len(parts) < 4:
            continue
        rel = parts[-1]
        if rel.startswith("b/"):
            rel = rel[2:]
        rel = rel.replace("\\", "/").strip()
        if not rel or rel in seen:
            continue
        seen.add(rel)
        paths.append(rel)
    if not paths:
        raise ApplyNotEligibleError("patch artifact contains no file paths")
    return paths


def _norm_rel(rel: str) -> str | None:
    if not isinstance(rel, str):
        return None
    text = rel.replace("\\", "/").strip()
    if (
        not text
        or text.startswith("/")
        or text.startswith("../")
        or "/../" in f"/{text}/"
        or ":" in text
    ):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _required_mark(root: Path, rel: str) -> dict[str, object]:
    mark = _file_mark(root, rel)
    if mark is None:
        raise ApplyNotEligibleError(f"illegal patch path {rel!r}")
    return mark


def _file_mark(root: Path, rel: str) -> dict[str, object] | None:
    safe = _norm_rel(rel)
    if safe is None:
        return None
    root = root.resolve()
    path = root.joinpath(*safe.split("/")).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return {"exists": False, "sha256": None}
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return {"exists": True, "sha256": hasher.hexdigest()}


def _matches_image(root: Path, image: dict) -> bool:
    for rel, expected in image.items():
        if not isinstance(expected, dict):
            return False
        actual = _file_mark(root, rel)
        if actual is None or actual != expected:
            return False
    return True
