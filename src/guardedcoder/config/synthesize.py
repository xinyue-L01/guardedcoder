from __future__ import annotations

import hashlib
import json
from typing import Any

from guardedcoder.models.config import AppConfig
from guardedcoder.models.envelope import Envelope

_ENVELOPE_FIELDS = (
    "read_paths",
    "write_paths",
    "profiles",
    "verify_profiles",
    "max_steps",
    "max_total_seconds",
    "allow_delete",
    "allow_network",
)


def synthesize_envelope(
    config: AppConfig,
    cli_overrides: dict[str, Any] | None = None,
) -> Envelope:
    values: dict[str, Any] = {name: getattr(config, name) for name in _ENVELOPE_FIELDS}
    if cli_overrides and "max_steps" in cli_overrides:
        values["max_steps"] = cli_overrides["max_steps"]
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    values["config_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Envelope(**values)
