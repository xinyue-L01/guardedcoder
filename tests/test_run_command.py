from __future__ import annotations

import sys
from pathlib import Path

from guardedcoder.models.envelope import CommandProfile
from guardedcoder.models.command_result import CommandResult
from guardedcoder.tools.run_command import run_command


def _profile(
    *argv: str,
    cwd: str = ".",
    timeout_seconds: int = 10,
    max_output_bytes: int = 4096,
) -> CommandProfile:
    return CommandProfile(
        profile_id="test",
        argv_template=argv,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        sensor=None,
    )


def test_timeout_sets_timed_out(tmp_path: Path) -> None:
    result = run_command(
        tmp_path,
        _profile(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            timeout_seconds=1,
        ),
        task_dir=tmp_path,
    )
    assert result.started is True
    assert result.timed_out is True
    assert result.exit_code is None
    assert not hasattr(result, "verdict")
    assert "PASS" not in CommandResult.model_fields
    assert "FAIL" not in CommandResult.model_fields


def test_start_failure_sets_started_false(tmp_path: Path) -> None:
    result = run_command(
        tmp_path,
        _profile("definitely-missing-command-guardedcoder-xyz"),
        task_dir=tmp_path,
    )
    assert result.started is False
    assert result.timed_out is False
    assert result.exit_code is None


def test_output_is_truncated(tmp_path: Path) -> None:
    result = run_command(
        tmp_path,
        _profile(
            sys.executable,
            "-c",
            "print('x' * 5000)",
            max_output_bytes=64,
        ),
        task_dir=tmp_path,
    )
    assert result.started is True
    assert result.timed_out is False
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) <= 64


def test_cwd_is_worktree_relative(tmp_path: Path) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    result = run_command(
        tmp_path,
        _profile(
            sys.executable,
            "-c",
            "import pathlib; print(pathlib.Path('.').resolve())",
            cwd="sub",
        ),
        task_dir=tmp_path,
    )
    assert result.started is True
    assert result.exit_code == 0
    assert str(nested.resolve()) in result.stdout


def test_junit_out_is_unique_per_run(tmp_path: Path) -> None:
    profile = _profile(
        sys.executable,
        "-c",
        "import sys; from pathlib import Path; Path(sys.argv[1]).write_text('<ok/>', encoding='utf-8')",
        "{junit_out}",
    )
    first = run_command(tmp_path, profile, task_dir=tmp_path)
    second = run_command(tmp_path, profile, task_dir=tmp_path)
    assert first.junit_path is not None
    assert second.junit_path is not None
    assert first.junit_path != second.junit_path
    assert Path(first.junit_path).parent == tmp_path
    assert Path(second.junit_path).parent == tmp_path
    assert Path(first.junit_path).is_file()
    assert Path(second.junit_path).is_file()
    assert "{junit_out}" not in first.junit_path


def test_command_result_has_no_pass_fail_fields() -> None:
    result = CommandResult(
        started=True,
        exit_code=0,
        timed_out=False,
        stdout="ok",
        stderr="",
        truncated=False,
        duration_seconds=0.01,
        junit_path=None,
    )
    dumped = result.model_dump()
    assert "PASS" not in dumped
    assert "FAIL" not in dumped
    assert set(dumped) == {
        "started",
        "exit_code",
        "timed_out",
        "stdout",
        "stderr",
        "truncated",
        "duration_seconds",
        "junit_path",
    }
