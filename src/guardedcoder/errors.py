class ActionParseError(Exception):
    """Raised when an LLM response cannot be parsed as a legal Action."""


class ConfigError(Exception):
    """Raised when user configuration is missing, malformed, or forbidden."""


class SecretLeakError(Exception):
    """Raised when a secret is detected in LLM messages."""


class RemoteKeyHttpError(Exception):
    """Raised when a configured key would be sent to a remote HTTP endpoint."""


class StaleRevisionError(Exception):
    """Raised when a task update does not match the expected state_revision."""


class PermitConsumedError(Exception):
    """Raised when a one-shot ExecutionPermit is consumed more than once."""


class PermitInvalidError(Exception):
    """Raised when a permit's envelope_hash does not match the current task."""


class ApprovalError(Exception):
    """Raised when approve fingerprint or bound revision does not match."""


class PendingConsumedError(Exception):
    """Raised when a PendingAction is consumed more than once."""
