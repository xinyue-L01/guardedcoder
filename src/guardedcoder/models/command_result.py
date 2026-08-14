from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    started: bool
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    truncated: bool
    duration_seconds: float
    junit_path: str | None = None
