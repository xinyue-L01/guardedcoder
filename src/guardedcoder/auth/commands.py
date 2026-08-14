from __future__ import annotations

import getpass
import hashlib
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

from guardedcoder.auth.keyring_store import KeyringStore
from guardedcoder.config.commands import resolve_config_path
from guardedcoder.config.load import load_app_config
from guardedcoder.errors import ConfigError


def handle_auth(
    args: Namespace,
    *,
    getpass_fn: Callable[..., str] | None = None,
    key_store: KeyringStore | None = None,
    config_path: Path | str | None = None,
    **_: object,
) -> int:
    config = load_app_config(resolve_config_path(config_path))
    provider_id = config.provider.provider_id
    store = key_store if key_store is not None else KeyringStore()
    command = args.auth_command
    if command in {"set", "update"}:
        reader = getpass_fn if getpass_fn is not None else getpass.getpass
        secret = reader("API Key: ")
        if not secret:
            raise ConfigError("empty key")
        store.set(provider_id, secret)
        return 0
    if command == "status":
        secret = store.get(provider_id)
        if secret:
            digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
            print(f"configured: yes\nprovider: {provider_id}\nfingerprint: {digest}")
        else:
            print(f"configured: no\nprovider: {provider_id}")
        return 0
    if command == "clear":
        store.clear(provider_id)
        return 0
    raise ConfigError(f"unknown auth command {command}")
