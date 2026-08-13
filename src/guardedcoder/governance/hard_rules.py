from __future__ import annotations

from guardedcoder.errors import ConfigError
from guardedcoder.models.config import AppConfig


def assert_hard_rules(config: AppConfig) -> None:
    for profile in config.profiles:
        tokens = {token.casefold() for token in profile.argv_template}
        if "pip" in tokens and "install" in tokens:
            raise ConfigError("hard-forbidden command profile: pip install")
        if "push" in tokens:
            raise ConfigError("hard-forbidden command profile: push")
        if "publish" in tokens:
            raise ConfigError("hard-forbidden command profile: publish")
