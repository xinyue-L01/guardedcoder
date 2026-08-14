from __future__ import annotations

import inspect

from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.verdict import VerdictStatus
from guardedcoder.sensors.exit_code import exit_code_verdict


def _result(**overrides: object) -> CommandResult:
    values: dict[str, object] = {
        "started": True,
        "exit_code": 0,
        "timed_out": False,
        "stdout": "ok",
        "stderr": "",
        "truncated": False,
        "duration_seconds": 0.25,
        "junit_path": None,
    }
    values.update(overrides)
    return CommandResult(**values)


def test_exit_zero_is_pass_and_nonzero_is_fail() -> None:
    passed = exit_code_verdict(_result(), profile_id="unit")
    failed = exit_code_verdict(_result(exit_code=2, stderr="bad"), profile_id="unit")

    assert passed.status is VerdictStatus.PASS
    assert failed.status is VerdictStatus.FAIL
    assert failed.exit_code == 2
    assert failed.output_sha256 != passed.output_sha256


def test_timeout_precedes_exit_code_and_not_started_is_error() -> None:
    timed_out = exit_code_verdict(
        _result(exit_code=None, timed_out=True), profile_id="unit"
    )
    not_started = exit_code_verdict(
        _result(started=False, exit_code=None), profile_id="unit"
    )

    assert timed_out.status is VerdictStatus.TIMEOUT
    assert not_started.status is VerdictStatus.ERROR


def test_exit_sensor_carries_bounded_diagnostics() -> None:
    verdict = exit_code_verdict(
        _result(stdout="x" * 5000, truncated=True), profile_id="lint"
    )

    assert len(verdict.summary.encode("utf-8")) <= 2048
    assert verdict.output_truncated is True
    assert verdict.sensor == "exit_code"


def test_command_result_does_not_encode_verdict_status() -> None:
    source = inspect.getsource(CommandResult)
    for token in ("PASS", "FAIL", "TIMEOUT", "ERROR"):
        assert token not in source

