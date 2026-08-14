from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path

from guardedcoder.errors import FenceError, FileToolError
from guardedcoder.governance.fence import FenceCode, check_path
from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.envelope import CommandProfile
from guardedcoder.tools.paths import resolve_under_worktree


def _bound_text(data: bytes | None, limit: int) -> tuple[str, bool]:
    raw = data or b""
    truncated = len(raw) > limit
    clipped = raw[:limit]
    return clipped.decode("utf-8", errors="replace"), truncated


def run_command(
    worktree: Path,
    profile: CommandProfile,
    *,
    task_dir: Path,
) -> CommandResult:
    fence = check_path(worktree, profile.cwd)
    if fence != FenceCode.ok:
        raise FenceError(fence)
    cwd = resolve_under_worktree(worktree, profile.cwd)
    if not cwd.is_dir():
        raise FileToolError("cwd is not a directory")

    task_dir.mkdir(parents=True, exist_ok=True)
    junit_path = task_dir / f"junit-{uuid.uuid4().hex}.xml"
    argv = [
        token.replace("{junit_out}", str(junit_path))
        for token in profile.argv_template
    ]

    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=profile.timeout_seconds,
        )
    except FileNotFoundError:
        return CommandResult(
            started=False,
            exit_code=None,
            timed_out=False,
            stdout="",
            stderr="",
            truncated=False,
            duration_seconds=time.monotonic() - started_at,
            junit_path=str(junit_path),
        )
    except OSError:
        return CommandResult(
            started=False,
            exit_code=None,
            timed_out=False,
            stdout="",
            stderr="",
            truncated=False,
            duration_seconds=time.monotonic() - started_at,
            junit_path=str(junit_path),
        )
    except subprocess.TimeoutExpired as exc:
        stdout, out_trunc = _bound_text(exc.stdout, profile.max_output_bytes)
        stderr, err_trunc = _bound_text(exc.stderr, profile.max_output_bytes)
        return CommandResult(
            started=True,
            exit_code=None,
            timed_out=True,
            stdout=stdout,
            stderr=stderr,
            truncated=out_trunc or err_trunc,
            duration_seconds=time.monotonic() - started_at,
            junit_path=str(junit_path),
        )

    stdout, out_trunc = _bound_text(completed.stdout, profile.max_output_bytes)
    stderr, err_trunc = _bound_text(completed.stderr, profile.max_output_bytes)
    return CommandResult(
        started=True,
        exit_code=completed.returncode,
        timed_out=False,
        stdout=stdout,
        stderr=stderr,
        truncated=out_trunc or err_trunc,
        duration_seconds=time.monotonic() - started_at,
        junit_path=str(junit_path),
    )
