from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from guardedcoder.models.envelope import CommandProfile


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProviderConfig(_FrozenStrict):
    provider_id: str
    base_url: str
    model: str
    timeout_seconds: int


class AppConfig(_FrozenStrict):
    config_schema_version: str
    provider: ProviderConfig
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    profiles: tuple[CommandProfile, ...]
    verify_profiles: tuple[str, ...]
    max_steps: int
    max_total_seconds: int
    command_timeout_seconds: int
    max_output_bytes: int
    max_patch_bytes: int
    allow_delete: bool
    allow_network: bool
