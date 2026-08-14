from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class VerdictStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class FailureEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    test_id: str
    message: str


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile_id: str
    sensor: str
    status: VerdictStatus
    exit_code: int | None
    summary: str
    failures: tuple[FailureEntry, ...] = ()
    output_truncated: bool
    output_sha256: str
    duration_seconds: float
    tests_total: int | None = None
    failures_count: int | None = None
    errors_count: int | None = None
    skipped_count: int | None = None

