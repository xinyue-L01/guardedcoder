from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from guardedcoder.errors import ConfigError
from guardedcoder.models.config import AppConfig
from guardedcoder.models.envelope import Envelope

_HARD_TOKENS = frozenset(
    {"push", "publish", "deploy", "sudo", "su", "runas", "pkexec"}
)


class ProfileKind(StrEnum):
    unknown = "unknown"
    hard_forbidden = "hard_forbidden"
    allowed = "allowed"


def _normalize_token(token: str) -> str:
    folded = token.casefold().replace("\\", "/")
    name = folded.rsplit("/", 1)[-1]
    return name.removesuffix(".exe")


def _is_pip_family(token: str) -> bool:
    if not token.startswith("pip"):
        return False
    return all(ch.isdigit() or ch == "." for ch in token[3:])


def argv_is_hard_forbidden(argv: Sequence[str]) -> bool:
    tokens = [_normalize_token(item) for item in argv]
    if any(item in _HARD_TOKENS for item in tokens):
        return True
    has_pip = any(_is_pip_family(item) for item in tokens)
    return has_pip and "install" in tokens


def classify_profile(envelope: Envelope, profile_id: str) -> ProfileKind:
    for profile in envelope.profiles:
        if profile.profile_id == profile_id:
            if argv_is_hard_forbidden(profile.argv_template):
                return ProfileKind.hard_forbidden
            return ProfileKind.allowed
    return ProfileKind.unknown


def assert_hard_rules(config: AppConfig) -> None:
    for profile in config.profiles:
        if argv_is_hard_forbidden(profile.argv_template):
            raise ConfigError(
                f"hard-forbidden command profile: {profile.profile_id}"
            )
