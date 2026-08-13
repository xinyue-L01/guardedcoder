from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CommandProfile(_FrozenStrict):
    profile_id: str
    argv_template: list[str]
    cwd: str
    timeout_seconds: int
    max_output_bytes: int
    sensor: str | None = None


class Envelope(_FrozenStrict):
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    profiles: tuple[CommandProfile, ...]
    verify_profiles: tuple[str, ...]
    max_steps: int
    max_total_seconds: int
    allow_delete: bool
    allow_network: bool
    config_digest: str
    envelope_hash: str = ""

    @model_validator(mode="after")
    def _fill_hash(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"envelope_hash"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        object.__setattr__(self, "envelope_hash", digest)
        return self
