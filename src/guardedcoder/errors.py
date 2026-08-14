from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guardedcoder.governance.fence import FenceCode


class ActionParseError(Exception):
    """Raised when an LLM response cannot be parsed as a legal Action."""


class ConfigError(Exception):
    """Raised when user configuration is missing, malformed, or forbidden."""


class SecretLeakError(Exception):
    """Raised when a secret is detected in LLM messages."""


class RemoteKeyHttpError(Exception):
    """Raised when a configured key would be sent to a remote HTTP endpoint."""


class KeyringError(Exception):
    """Raised when the OS keyring is unavailable or a credential operation fails."""


class StaleRevisionError(Exception):
    """Raised when a task update does not match the expected state_revision."""


class PermitConsumedError(Exception):
    """Raised when a one-shot ExecutionPermit is consumed more than once."""


class PermitInvalidError(Exception):
    """Raised when a permit's envelope, revision, or pending binding is invalid."""


class ExecutionWindowOpenError(Exception):
    """Raised when a task already has an active execution window."""


class ApprovalError(Exception):
    """Raised when approve fingerprint or bound revision does not match."""


class PendingConsumedError(Exception):
    """Raised when a PendingAction is consumed more than once."""


class FileToolError(ValueError):
    """Raised when a file tool cannot safely process a path."""


class FenceError(FileToolError):
    """Raised when a file tool path fails the workspace fence."""

    def __init__(self, code: FenceCode) -> None:
        self.code = code
        super().__init__(code.value)


class PatchError(FileToolError):
    """Raised when a unified diff cannot be previewed or applied atomically."""


class UnauthorizedError(Exception):
    """Raised when M5 is invoked without a consumed permit, window, or claim."""


class ClaimConflictError(Exception):
    """Raised when an exclusive recovered-attempt claim is already held."""
