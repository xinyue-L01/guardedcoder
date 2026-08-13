from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

_KEY_SHAPED = re.compile(r"sk-[A-Za-z0-9_-]+")


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    body: str
    truncated: bool
    artifact_sha256: str | None = None
    artifact_path: str | None = None

    @field_validator("body")
    @classmethod
    def _redact_key_shaped_text(cls, value: str) -> str:
        return _KEY_SHAPED.sub("***", value)
