from __future__ import annotations

import hashlib

from guardedcoder.models.command_result import CommandResult

_SUMMARY_LIMIT = 2048


def output_digest(result: CommandResult) -> str:
    payload = result.stdout.encode("utf-8") + b"\0" + result.stderr.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def bounded_summary(value: str, *, limit: int = _SUMMARY_LIMIT) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= limit:
        return value
    suffix = "...[truncated]"
    budget = limit - len(suffix.encode("utf-8"))
    clipped = raw[:budget]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix


def diagnostic_text(result: CommandResult) -> str:
    return result.stderr or result.stdout or "no command output"

