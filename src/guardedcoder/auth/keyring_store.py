from __future__ import annotations

from typing import Protocol

from guardedcoder.errors import KeyringError

SERVICE_NAME = "guardedcoder"


class KeyringBackend(Protocol):
    def set_password(self, service: str, username: str, password: str) -> None: ...

    def get_password(self, service: str, username: str) -> str | None: ...

    def delete_password(self, service: str, username: str) -> None: ...


def _default_backend() -> KeyringBackend:
    try:
        import keyring
    except Exception:
        raise KeyringError("keyring unavailable") from None
    return keyring


def _is_missing_entry(exc: BaseException) -> bool:
    if isinstance(exc, KeyError):
        return True
    if exc.__class__.__name__ != "PasswordDeleteError":
        return False
    text = str(exc).casefold()
    return "not found" in text or "no such" in text


class KeyringStore:
    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else _default_backend()

    def set(self, provider_id: str, secret: str) -> None:
        try:
            self._backend.set_password(SERVICE_NAME, provider_id, secret)
        except KeyringError:
            raise
        except Exception:
            raise KeyringError("keyring unavailable") from None

    def get(self, provider_id: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE_NAME, provider_id)
        except KeyringError:
            raise
        except Exception:
            raise KeyringError("keyring unavailable") from None

    def clear(self, provider_id: str) -> None:
        try:
            self._backend.delete_password(SERVICE_NAME, provider_id)
        except KeyringError:
            raise
        except Exception as exc:
            if _is_missing_entry(exc):
                return
            raise KeyringError("keyring unavailable") from None
