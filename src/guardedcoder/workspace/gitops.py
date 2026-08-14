from __future__ import annotations

import subprocess
from pathlib import Path


class GitOperationError(RuntimeError):
    """Raised when a trusted Git lifecycle command fails."""


class DirtyWorktreeError(GitOperationError):
    """Raised when tracked or untracked user content makes a tree dirty."""


def git_text(repo: str | Path, *args: str) -> str:
    """Run Git without a shell and return decoded stdout."""
    command = ["git", "-C", str(repo), *args]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
        )
    except OSError as exc:
        raise GitOperationError("unable to start git") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitOperationError(
            f"git command failed with exit code {completed.returncode}: {detail}"
        )
    return completed.stdout.strip()


def repo_real_path(repo_path: str | Path) -> Path:
    requested = Path(repo_path).expanduser().resolve()
    top_level = git_text(requested, "rev-parse", "--show-toplevel")
    if not top_level:
        raise GitOperationError("git did not return a repository root")
    return Path(top_level).resolve()


def assert_clean(repo_path: str | Path) -> Path:
    """Return the real repository root only when all user content is committed."""
    root = repo_real_path(repo_path)
    status = git_text(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    if status:
        raise DirtyWorktreeError(
            "repository has tracked or untracked changes; refusing to alter them"
        )
    return root
