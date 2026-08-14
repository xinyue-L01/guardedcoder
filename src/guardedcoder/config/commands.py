from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from guardedcoder.config.load import load_app_config
from guardedcoder.config.paths import user_config_path
from guardedcoder.config.template import DEFAULT_CONFIG_TOML
from guardedcoder.errors import ConfigError


def resolve_config_path(config_path: Path | str | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)
    return user_config_path()


def init_config(path: Path) -> None:
    if path.exists():
        raise ConfigError(f"config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")


def handle_config(
    args: Namespace,
    *,
    config_path: Path | str | None = None,
    **_: object,
) -> int:
    path = resolve_config_path(config_path)
    command = args.config_command
    if command == "init":
        init_config(path)
        return 0
    config = load_app_config(path)
    if command == "validate":
        print("valid")
        return 0
    if command == "show":
        print(json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    raise ConfigError(f"unknown config command {command}")
