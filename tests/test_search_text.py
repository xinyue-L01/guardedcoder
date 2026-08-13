from pathlib import Path

from guardedcoder.tools.search_text import (
    MAX_FILES,
    MAX_MATCHES,
    MAX_OUTPUT_BYTES,
    search_text,
)


def test_search_text_returns_path_line_number_and_matching_line(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("nothing\nneedle beta\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle alpha\n", encoding="utf-8")

    result = search_text(tmp_path, "needle")

    assert result.body.splitlines() == [
        "a.txt:1:needle alpha",
        "b.txt:2:needle beta",
    ]
    assert result.truncated is False


def test_search_text_limits_matches_to_50(tmp_path: Path) -> None:
    assert MAX_MATCHES == 50
    (tmp_path / "many.txt").write_text(
        "".join(f"needle {index}\n" for index in range(MAX_MATCHES + 1)),
        encoding="utf-8",
    )

    result = search_text(tmp_path, "needle")

    assert len(result.body.splitlines()) == MAX_MATCHES
    assert result.truncated is True


def test_search_text_limits_files_to_64(tmp_path: Path) -> None:
    assert MAX_FILES == 64
    for index in range(MAX_FILES + 1):
        (tmp_path / f"{index:03}.txt").write_text("haystack\n", encoding="utf-8")

    result = search_text(tmp_path, "missing")

    assert result.body == ""
    assert result.truncated is True


def test_search_text_limits_utf8_output_bytes(tmp_path: Path) -> None:
    assert MAX_OUTPUT_BYTES == 65_536
    (tmp_path / "large.txt").write_text(
        "needle " + ("界" * MAX_OUTPUT_BYTES) + "\n",
        encoding="utf-8",
    )

    result = search_text(tmp_path, "needle")

    assert len(result.body.encode("utf-8")) <= MAX_OUTPUT_BYTES
    assert result.truncated is True


def test_search_text_skips_env_files_without_leaking(tmp_path: Path) -> None:
    fake_key = "sk" + "-test-needle"
    (tmp_path / ".env").write_text(f"TOKEN={fake_key}\n", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env.local").write_text(f"TOKEN={fake_key}\n", encoding="utf-8")
    (tmp_path / "safe.txt").write_text("needle safe\n", encoding="utf-8")

    result = search_text(tmp_path, "needle")

    assert result.body == "safe.txt:1:needle safe"
    assert fake_key not in result.body
    assert ".env" not in result.body


def test_search_text_skips_binary_and_invalid_utf8_files(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"needle\x00hidden\n")
    (tmp_path / "invalid.dat").write_bytes(b"needle\xffhidden\n")
    (tmp_path / "safe.txt").write_text("needle visible\n", encoding="utf-8")

    result = search_text(tmp_path, "needle")

    assert result.body == "safe.txt:1:needle visible"
