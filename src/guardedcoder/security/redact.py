from __future__ import annotations

import re

_PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN[ A-Z0-9]*(?:PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
)
_TOKEN_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+"),
    re.compile(
        r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,255}|"
        r"github_pat_[A-Za-z0-9_]{20,255})(?![A-Za-z0-9_])"
    ),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_-]{20,}"),
)
_LABELED_SECRET = re.compile(
    r"(?i)(?P<label>\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|password|passwd|secret)\b\s*[:=]\s*)"
    r"(?P<value>(?:bearer\s+)?[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")


def redact_text(value: str, *, replacement: str = "[redacted]") -> str:
    """Remove common credential shapes without returning matched values."""
    if _PRIVATE_KEY_HEADER.search(value):
        return replacement

    redacted = value
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = _LABELED_SECRET.sub(
        lambda match: f"{match.group('label')}{replacement}", redacted
    )
    return _BEARER.sub(f"Bearer {replacement}", redacted)
