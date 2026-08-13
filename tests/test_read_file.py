from pathlib import Path

import pytest
from pydantic import ValidationError

from guardedcoder.errors import FenceError, FileToolError
from guardedcoder.governance.fence import FenceCode
from guardedcoder.models.observation import Observation
from guardedcoder.tools.read_file import MAX_BYTES, read_file


def test_read_file_returns_utf8_text(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_bytes("hello\n世界\n".encode())

    result = read_file(tmp_path, "note.txt")

    assert result == Observation(body="hello\n世界\n", truncated=False)
    assert result.artifact_sha256 is None
    assert result.artifact_path is None


def test_read_file_truncates_after_65536_bytes(tmp_path: Path) -> None:
    assert MAX_BYTES == 65_536
    (tmp_path / "large.txt").write_bytes(b"x" * (MAX_BYTES + 1))

    result = read_file(tmp_path, "large.txt")

    assert result.body == "x" * MAX_BYTES
    assert result.truncated is True


@pytest.mark.parametrize("body", [b"text\x00tail", b"\xff"])
def test_read_file_rejects_binary_or_invalid_utf8(tmp_path: Path, body: bytes) -> None:
    (tmp_path / "binary.dat").write_bytes(body)

    with pytest.raises(FileToolError):
        read_file(tmp_path, "binary.dat")


@pytest.mark.parametrize("name", [".env", ".env.local"])
def test_read_file_rejects_sensitive_env_without_leaking(
    tmp_path: Path, name: str
) -> None:
    fake_key = "sk" + "-test-sensitive"
    (tmp_path / name).write_text(f"API_KEY={fake_key}\n", encoding="utf-8")

    with pytest.raises(FenceError) as caught:
        read_file(tmp_path, name)

    assert caught.value.code == FenceCode.SENSITIVE_PATH
    assert fake_key not in str(caught.value)


def test_read_file_rejects_workspace_escape_without_leaking(tmp_path: Path) -> None:
    fake_key = "sk" + "-test-outside"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (tmp_path / "outside.txt").write_text(fake_key, encoding="utf-8")

    with pytest.raises(FenceError) as caught:
        read_file(worktree, "../outside.txt")

    assert caught.value.code == FenceCode.WORKSPACE_ESCAPE
    assert fake_key not in str(caught.value)


def test_observation_is_frozen_strict_and_forbids_extra_fields() -> None:
    result = Observation(body="ok", truncated=False)
    with pytest.raises(ValidationError):
        result.body = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Observation(body="ok", truncated=0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Observation(body="ok", truncated=False, extra=True)  # type: ignore[call-arg]


def test_observation_redacts_key_shaped_body() -> None:
    fake_key = "sk" + "-test-observation"

    result = Observation(body=f"token={fake_key}", truncated=False)

    assert fake_key not in result.body


def test_read_file_line_range_reads_selected_lines(tmp_path: Path) -> None:
    (tmp_path / "lines.txt").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file(tmp_path, "lines.txt", start_line=2, end_line=3)

    assert result.body.splitlines() == ["two", "three"]
    assert result.truncated is False


def test_read_file_rejects_invalid_utf8_without_file_bytes_in_cause(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.dat").write_bytes(b"ok\xff")

    with pytest.raises(FileToolError) as caught:
        read_file(tmp_path, "bad.dat")

    assert caught.value.__cause__ is None
    assert "ok" not in repr(caught.value)
    assert "\\xff" not in repr(caught.value)


def test_observation_does_not_redact_task_filenames() -> None:
    result = Observation(body="task-21-report.md", truncated=False)

    assert result.body == "task-21-report.md"


def test_read_file_byte_limit_holds_after_key_redaction(tmp_path: Path) -> None:
    fake_key = "sk" + "-test"
    prefix = (fake_key + "\n").encode()
    (tmp_path / "key.txt").write_bytes(
        prefix + (b"x" * (MAX_BYTES + 1 - len(prefix)))
    )

    result = read_file(tmp_path, "key.txt")

    assert len(result.body.encode("utf-8")) <= MAX_BYTES
    assert fake_key not in result.body
    assert result.truncated is True
