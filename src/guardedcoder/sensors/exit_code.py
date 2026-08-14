from __future__ import annotations

from guardedcoder.models.command_result import CommandResult
from guardedcoder.models.verdict import Verdict, VerdictStatus
from guardedcoder.sensors.common import bounded_summary, diagnostic_text, output_digest


def exit_code_verdict(result: CommandResult, *, profile_id: str) -> Verdict:
    if not result.started:
        status = VerdictStatus.ERROR
        description = "command did not start"
    elif result.timed_out:
        status = VerdictStatus.TIMEOUT
        description = "command timed out"
    elif result.exit_code == 0:
        status = VerdictStatus.PASS
        description = "command exited successfully"
    elif result.exit_code is None:
        status = VerdictStatus.ERROR
        description = "command result has no exit code"
    else:
        status = VerdictStatus.FAIL
        description = f"command exited with code {result.exit_code}"

    detail = diagnostic_text(result)
    return Verdict(
        profile_id=profile_id,
        sensor="exit_code",
        status=status,
        exit_code=result.exit_code,
        summary=bounded_summary(f"{description}: {detail}"),
        output_truncated=result.truncated,
        output_sha256=output_digest(result),
        duration_seconds=result.duration_seconds,
    )

