from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from guardedcoder.security.redact import redact_text


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    body: str
    truncated: bool
    artifact_sha256: str | None = None
    artifact_path: str | None = None

    @field_validator("body")
    @classmethod
    def _redact_key_shaped_text(cls, value: str) -> str:
        return redact_text(value, replacement="***")
