from pathlib import Path

import pytest

from guardedcoder.governance.fence import FenceCode, check_path


def test_parent_traversal_is_workspace_escape(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    result = check_path(tmp_path, "../secret")
    assert result == FenceCode.WORKSPACE_ESCAPE
    assert result == "WORKSPACE_ESCAPE"


def test_out_of_tree_symlink_is_workspace_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    link = worktree / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows cannot create symlink")
    result = check_path(worktree, "escape")
    assert result == FenceCode.WORKSPACE_ESCAPE


def test_env_file_is_sensitive_path(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("x", encoding="utf-8")
    result = check_path(tmp_path, ".env")
    assert result == FenceCode.SENSITIVE_PATH
    assert result == "SENSITIVE_PATH"


def test_env_dot_file_is_sensitive_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / ".env.local").write_text("x", encoding="utf-8")
    result = check_path(tmp_path, "src/.env.local")
    assert result == FenceCode.SENSITIVE_PATH


def test_in_tree_normal_path_is_ok(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("print(1)\n", encoding="utf-8")
    result = check_path(tmp_path, "src/foo.py")
    assert result == FenceCode.ok
    assert result == "ok"
