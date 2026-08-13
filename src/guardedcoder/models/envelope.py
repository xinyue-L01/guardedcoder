from __future__ import annotations

import hashlib
import json
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def _freeze_str_seq(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        items = tuple(value)
        if not all(isinstance(item, str) for item in items):
            raise TypeError("sequence items must be str")
        return items
    raise TypeError("expected list[str] or tuple[str, ...]")


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CommandProfile(_FrozenStrict):
    profile_id: str
    argv_template: Annotated[tuple[str, ...], BeforeValidator(_freeze_str_seq)]
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
