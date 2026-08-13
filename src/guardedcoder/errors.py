class ActionParseError(Exception):
    """Raised when an LLM response cannot be parsed as a legal Action."""


class SecretLeakError(Exception):
    """Raised when a secret is detected in LLM messages."""
