from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from guardedcoder.errors import ConfigError
from guardedcoder.models.config import AppConfig

_SECRET_KEYS = frozenset({"api_key", "token", "password"})
_PEM_PRIVATE_KEY = re.compile(r"-----BEGIN[ A-Z0-9]*PRIVATE KEY-----")


def load_app_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}") from exc
    _reject_forbidden(data)
    try:
        return AppConfig.model_validate(_freeze_lists(data))
    except (ValidationError, TypeError) as exc:
        raise ConfigError(f"invalid config {path}") from exc


def _reject_forbidden(obj: object) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = key.lower() if isinstance(key, str) else ""
            if lowered in _SECRET_KEYS:
                raise ConfigError(f"secret-like field {key!r} is not allowed")
            if lowered == "shell" and value:
                raise ConfigError("shell strings are not allowed")
            if lowered == "cmdline":
                raise ConfigError("unstructured cmdline is not allowed")
            if lowered == "argv_template" and isinstance(value, str):
                raise ConfigError("argv_template must be a list, not a shell string")
            if isinstance(value, str) and _PEM_PRIVATE_KEY.search(value):
                raise ConfigError("secret-like PEM private key value is not allowed")
            _reject_forbidden(value)
        return
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, str) and _PEM_PRIVATE_KEY.search(item):
                raise ConfigError("secret-like PEM private key value is not allowed")
            _reject_forbidden(item)


def _freeze_lists(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _freeze_lists(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return tuple(_freeze_lists(item) for item in obj)
    return obj
