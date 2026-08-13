class ActionParseError(Exception):
    """Raised when an LLM response cannot be parsed as a legal Action."""


class ConfigError(Exception):
    """Raised when user configuration is missing, malformed, or forbidden."""
