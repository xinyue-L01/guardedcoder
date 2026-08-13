from pathlib import Path

import pytest

from guardedcoder.errors import FenceError
from guardedcoder.governance.fence import FenceCode
from guardedcoder.tools.list_dir import MAX_ENTRIES, list_dir


def test_list_dir_lists_one_level_in_name_order(tmp_path: Path) -> None:
    directory = tmp_path / "src"
    nested = directory / "nested"
    nested.mkdir(parents=True)
    (directory / "b.py").write_text("b\n", encoding="utf-8")
    (directory / "a.py").write_text("a\n", encoding="utf-8")
    (nested / "hidden.py").write_text("hidden\n", encoding="utf-8")

    result = list_dir(tmp_path, "src")

    assert result.body.splitlines() == ["a.py", "b.py", "nested"]
    assert result.truncated is False


def test_list_dir_limits_entries_to_256(tmp_path: Path) -> None:
    assert MAX_ENTRIES == 256
    directory = tmp_path / "many"
    directory.mkdir()
    for index in range(MAX_ENTRIES + 1):
        (directory / f"{index:03}.txt").touch()

    result = list_dir(tmp_path, "many")

    assert len(result.body.splitlines()) == MAX_ENTRIES
    assert result.truncated is True


def test_list_dir_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(FenceError) as caught:
        list_dir(tmp_path, "../outside")

    assert caught.value.code == FenceCode.WORKSPACE_ESCAPE


def test_list_dir_omits_sensitive_env_names(tmp_path: Path) -> None:
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (directory / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    (directory / "app.toml").write_text("ok\n", encoding="utf-8")

    result = list_dir(tmp_path, "cfg")

    assert result.body.splitlines() == ["app.toml"]
    assert ".env" not in result.body
