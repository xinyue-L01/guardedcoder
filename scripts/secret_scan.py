"""Scan a workspace for common credential shapes without printing secrets."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SecretRule:
    name: str
    pattern: re.Pattern[bytes]


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    rule: str


@dataclass(frozen=True, slots=True)
class ScanError:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class ScanReport:
    root: Path
    findings: tuple[Finding, ...]
    errors: tuple[ScanError, ...]
    scanned_files: int

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 2
        if self.findings:
            return 1
        return 0


_PRIVATE_KEY_HEADERS = tuple(
    ("-----BEGIN " + key_type + "-----").encode("ascii")
    for key_type in (
        "PRIVATE KEY",
        "RSA PRIVATE KEY",
        "EC PRIVATE KEY",
        "DSA PRIVATE KEY",
        "OPENSSH PRIVATE KEY",
        "PGP PRIVATE KEY BLOCK",
    )
)

RULES: tuple[SecretRule, ...] = (
    SecretRule(
        "private-key-header",
        re.compile(b"|".join(re.escape(header) for header in _PRIVATE_KEY_HEADERS)),
    ),
    SecretRule(
        "aws-access-key-id",
        re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    ),
    SecretRule(
        "github-token",
        re.compile(
            rb"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{36,255}|"
            rb"github_pat_[A-Za-z0-9_]{82,255})(?![A-Za-z0-9_])"
        ),
    ),
    SecretRule(
        "openai-api-key",
        re.compile(
            rb"(?<![A-Za-z0-9])sk-(?:(?:proj|svcacct)-)?"
            rb"[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
        ),
    ),
    SecretRule(
        "google-api-key",
        re.compile(rb"(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    ),
    SecretRule(
        "slack-token",
        re.compile(
            rb"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}"
            rb"(?![A-Za-z0-9-])"
        ),
    ),
    SecretRule(
        "stripe-live-secret-key",
        re.compile(rb"(?<![A-Za-z0-9])sk_live_[A-Za-z0-9]{24,}(?![A-Za-z0-9])"),
    ),
    SecretRule(
        "gitlab-token",
        re.compile(rb"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    ),
)

_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "htmlcov",
        "node_modules",
        "venv",
    }
)
_EXCLUDED_FILE_NAMES = frozenset({".coverage", ".git"})


def _is_excluded_directory(name: str) -> bool:
    normalized = name.casefold()
    return (
        normalized in _EXCLUDED_DIRECTORY_NAMES
        or normalized.endswith(".egg-info")
    )


def _walk_error(error: OSError, errors: list[ScanError], root: Path) -> None:
    error_path = Path(error.filename).resolve() if error.filename else root
    errors.append(ScanError(path=error_path, reason=str(error)))


def scan_workspace(root: str | Path) -> ScanReport:
    workspace = Path(root).resolve()
    if not workspace.is_dir():
        return ScanReport(
            root=workspace,
            findings=(),
            errors=(ScanError(workspace, "workspace is not a readable directory"),),
            scanned_files=0,
        )

    findings: list[Finding] = []
    errors: list[ScanError] = []
    scanned_files = 0

    def record_walk_error(error: OSError) -> None:
        _walk_error(error, errors, workspace)

    for current, directory_names, file_names in os.walk(
        workspace, topdown=True, onerror=record_walk_error, followlinks=False
    ):
        directory_names[:] = sorted(
            name for name in directory_names if not _is_excluded_directory(name)
        )
        current_path = Path(current)
        for file_name in sorted(file_names):
            if file_name.casefold() in _EXCLUDED_FILE_NAMES:
                continue

            candidate = current_path / file_name
            if candidate.is_symlink():
                continue
            try:
                content = candidate.read_bytes()
            except OSError as error:
                errors.append(ScanError(path=candidate, reason=str(error)))
                continue

            scanned_files += 1
            for rule in RULES:
                if rule.pattern.search(content):
                    findings.append(Finding(path=candidate, rule=rule.name))

    return ScanReport(
        root=workspace,
        findings=tuple(findings),
        errors=tuple(errors),
        scanned_files=scanned_files,
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan a workspace for private keys and common API key shapes."
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="workspace to scan (default: current directory)",
    )
    args = parser.parse_args(argv)

    report = scan_workspace(args.workspace)
    for finding in report.findings:
        print(
            f"secret detected: {_display_path(finding.path, report.root)} "
            f"({finding.rule})",
            file=sys.stderr,
        )
    for error in report.errors:
        print(
            f"scan error: {_display_path(error.path, report.root)}: {error.reason}",
            file=sys.stderr,
        )

    if report.exit_code == 0:
        print(f"secret scan clean: {report.scanned_files} files")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
