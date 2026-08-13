from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from guardedcoder.workspace.gitops import GitOperationError, git_text
from guardedcoder.workspace.worktree import validate_task_id


@dataclass(frozen=True)
class PatchArtifact:
    body: bytes
    sha256: str
    path: Path
    over_limit: bool

    @property
    def can_mark_patch_ready(self) -> bool:
        return not self.over_limit

    def summary(self, *, max_bytes: int) -> str:
        prefix = f"sha256={self.sha256}\npath={self.path}\n"
        decoded = self.body.decode("utf-8", errors="replace")
        marked_false = f"truncated=false\n{prefix}{decoded}"
        if len(marked_false.encode("utf-8")) <= max(0, max_bytes):
            return marked_false
        head = f"truncated=true\n{prefix}"
        budget = max(0, max_bytes - len(head.encode("utf-8")))
        preview = decoded.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
        return head + preview


class PatchArtifactPort(Protocol):
    def export(self, task: object) -> PatchArtifact: ...


class GitPatchArtifactPort:
    def __init__(self, *, artifact_dir: str | Path) -> None:
        self._artifact_dir = Path(artifact_dir)

    def export(self, task: object) -> PatchArtifact:
        task_id = str(getattr(task, "task_id"))
        validate_task_id(task_id)
        worktree = Path(getattr(task, "worktree_identity")).expanduser().resolve()
        base_commit = str(getattr(task, "base_commit"))
        max_patch_bytes = int(getattr(task, "max_patch_bytes"))
        body = _complete_diff(worktree, base_commit)
        digest = hashlib.sha256(body).hexdigest()
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self._artifact_dir / f"{task_id}.patch"
        path.write_bytes(body)
        return PatchArtifact(
            body=body,
            sha256=digest,
            path=path.resolve(),
            over_limit=len(body) > max_patch_bytes,
        )


def _complete_diff(worktree: Path, base_commit: str) -> bytes:
    git_dir = git_text(worktree, "rev-parse", "--absolute-git-dir")
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / "index"
        env = os.environ.copy()
        env["GIT_DIR"] = git_dir
        env["GIT_WORK_TREE"] = str(worktree)
        env["GIT_INDEX_FILE"] = str(index)
        _git_env(env, worktree, "read-tree", base_commit)
        _git_env(env, worktree, "add", "-A")
        return _git_env(
            env,
            worktree,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-color",
            base_commit,
            allow_diff=True,
        )


def _git_env(
    env: dict[str, str],
    cwd: Path,
    *args: str,
    allow_diff: bool = False,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=env,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise GitOperationError("unable to start git") from exc
    ok = {0, 1} if allow_diff else {0}
    if completed.returncode not in ok:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitOperationError(
            f"git command failed with exit code {completed.returncode}: {detail}"
        )
    return completed.stdout
