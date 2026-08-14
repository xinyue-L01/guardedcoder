from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import secret_scan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCANNER = PROJECT_ROOT / "scripts" / "secret_scan.py"


def _fake_api_keys() -> tuple[str, ...]:
    return (
        "AK" + "IA" + ("A" * 16),
        "gh" + "p_" + ("a" * 36),
        "s" + "k-" + ("b" * 32),
        "AI" + "za" + ("C" * 35),
        "xo" + "xb-" + "1234567890-1234567890-" + ("d" * 24),
    )


def _private_key_header() -> str:
    return "-----BEGIN " + "PRIVATE KEY-----"


def _run_scanner(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), str(root)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize("secret", _fake_api_keys())
def test_scan_workspace_detects_typical_api_key_shapes(
    tmp_path: Path, secret: str
) -> None:
    candidate = tmp_path / "settings.txt"
    candidate.write_text(f"token={secret}\n", encoding="utf-8")

    report = secret_scan.scan_workspace(tmp_path)

    assert report.exit_code == 1
    assert [finding.path for finding in report.findings] == [candidate.resolve()]
    assert not report.errors


def test_scan_workspace_detects_secret_in_nested_non_excluded_directory(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "pkg" / "leaked.txt"
    candidate.parent.mkdir()
    candidate.write_text(_fake_api_keys()[0], encoding="ascii")

    report = secret_scan.scan_workspace(tmp_path)

    assert report.exit_code == 1
    assert [finding.path for finding in report.findings] == [candidate.resolve()]
    assert not report.errors


def test_scan_workspace_detects_private_key_header_in_binary_file(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "archive.bin"
    candidate.write_bytes(
        b"\x00\xffpayload\x00" + _private_key_header().encode("ascii") + b"\x00"
    )

    report = secret_scan.scan_workspace(tmp_path)

    assert report.exit_code == 1
    assert len(report.findings) == 1
    assert report.findings[0].path == candidate.resolve()
    assert report.findings[0].rule == "private-key-header"


def test_scan_workspace_accepts_clean_text_and_binary_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ordinary configuration\n", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\x00\xff\x10ordinary binary payload")

    report = secret_scan.scan_workspace(tmp_path)

    assert report.exit_code == 0
    assert not report.findings
    assert not report.errors


@pytest.mark.parametrize(
    "directory_name",
    (
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".superpowers",
        "node_modules",
        "dist",
        "build",
        "package.egg-info",
    ),
)
def test_scan_workspace_ignores_excluded_directories(
    tmp_path: Path, directory_name: str
) -> None:
    excluded = tmp_path / directory_name
    excluded.mkdir()
    (excluded / "generated.txt").write_text(_fake_api_keys()[0], encoding="ascii")

    report = secret_scan.scan_workspace(tmp_path)

    assert report.exit_code == 0
    assert not report.findings
    assert not report.errors


def test_scan_workspace_reports_unreadable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("content", encoding="utf-8")
    blocked_resolved = blocked.resolve()
    original_read_bytes = Path.read_bytes

    def deny_blocked_file(path: Path) -> bytes:
        if path.resolve() == blocked_resolved:
            raise PermissionError("access denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_blocked_file)

    report = secret_scan.scan_workspace(tmp_path)
    exit_code = secret_scan.main([str(tmp_path)])

    assert report.exit_code == 2
    assert not report.findings
    assert [error.path for error in report.errors] == [blocked_resolved]
    assert exit_code == 2
    assert "blocked.txt" in capsys.readouterr().err


def test_cli_uses_distinct_clean_finding_and_error_exit_codes(tmp_path: Path) -> None:
    clean = _run_scanner(tmp_path)
    (tmp_path / "credential.txt").write_text(_fake_api_keys()[1], encoding="ascii")
    finding = _run_scanner(tmp_path)
    missing = _run_scanner(tmp_path / "missing")

    assert clean.returncode == 0
    assert finding.returncode == 1
    assert "credential.txt" in finding.stderr
    assert _fake_api_keys()[1] not in finding.stderr
    assert _fake_api_keys()[1] not in finding.stdout
    assert missing.returncode == 2


def test_repository_contains_no_detectable_secret_shapes() -> None:
    report = secret_scan.scan_workspace(PROJECT_ROOT)

    assert not report.findings
    assert not report.errors
