from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from guardedcoder.errors import FenceError, PatchError
from guardedcoder.governance.fence import FenceCode
from guardedcoder.tools.apply_patch import apply_patch


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _modify_diff(path: str, old: str, new: str) -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def test_apply_patch_modifies_one_file_and_records_images(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"old\n")

    result = apply_patch(tmp_path, _modify_diff("a.txt", "old", "new"))

    assert (tmp_path / "a.txt").read_bytes() == b"new\n"
    assert result.preimage == {"a.txt": {"exists": True, "sha256": _sha(b"old\n")}}
    assert result.postimage == {"a.txt": {"exists": True, "sha256": _sha(b"new\n")}}
    assert result.observation.truncated is False
    assert "a.txt" in result.observation.body


def test_two_file_second_hunk_fail_changes_zero_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"keep-a\n")
    (tmp_path / "b.txt").write_bytes(b"keep-b\n")
    diff = (
        _modify_diff("a.txt", "keep-a", "changed-a")
        + _modify_diff("b.txt", "wrong-old", "changed-b")
    )

    with pytest.raises(PatchError):
        apply_patch(tmp_path, diff)

    assert (tmp_path / "a.txt").read_bytes() == b"keep-a\n"
    assert (tmp_path / "b.txt").read_bytes() == b"keep-b\n"


def test_create_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"keep\n")
    diff = "--- /dev/null\n+++ b/a.txt\n@@ -0,0 +1,1 @@\n+new\n"

    with pytest.raises(PatchError):
        apply_patch(tmp_path, diff)

    assert (tmp_path / "a.txt").read_bytes() == b"keep\n"


def test_malformed_diff_changes_zero_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"stay\n")

    with pytest.raises(PatchError):
        apply_patch(tmp_path, "this is not a unified diff\n")

    assert (tmp_path / "a.txt").read_bytes() == b"stay\n"


def test_sensitive_env_is_fenced_and_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / ".env").write_bytes(b"x=1\n")

    with pytest.raises(FenceError) as caught:
        apply_patch(tmp_path, _modify_diff(".env", "x=1", "x=2"))

    assert caught.value.code == FenceCode.SENSITIVE_PATH
    assert (tmp_path / ".env").read_bytes() == b"x=1\n"


def test_path_escape_is_fenced_and_writes_nothing(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "in.txt").write_bytes(b"in\n")
    (tmp_path / "outside.txt").write_bytes(b"out\n")

    with pytest.raises(FenceError) as caught:
        apply_patch(worktree, _modify_diff("../outside.txt", "out", "hacked"))

    assert caught.value.code == FenceCode.WORKSPACE_ESCAPE
    assert (tmp_path / "outside.txt").read_bytes() == b"out\n"
    assert (worktree / "in.txt").read_bytes() == b"in\n"


def test_symlink_target_is_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret\n")
    link = worktree / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires privilege on this Windows host")

    with pytest.raises((FenceError, PatchError)):
        apply_patch(worktree, _modify_diff("link.txt", "secret", "leaked"))

    assert outside.read_bytes() == b"secret\n"


def test_delete_requires_allow_delete(tmp_path: Path) -> None:
    (tmp_path / "gone.txt").write_bytes(b"bye\n")
    diff = (
        "--- a/gone.txt\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-bye\n"
    )

    with pytest.raises(PatchError):
        apply_patch(tmp_path, diff)

    assert (tmp_path / "gone.txt").read_bytes() == b"bye\n"

    result = apply_patch(tmp_path, diff, allow_delete=True)
    assert not (tmp_path / "gone.txt").exists()
    assert result.preimage == {"gone.txt": {"exists": True, "sha256": _sha(b"bye\n")}}
    assert result.postimage == {"gone.txt": {"exists": False, "sha256": None}}


def test_rename_is_atomic(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_bytes(b"moved\n")
    diff = (
        "diff --git a/old.txt b/new.txt\n"
        "rename from old.txt\n"
        "rename to new.txt\n"
        "--- a/old.txt\n"
        "+++ b/new.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-moved\n"
        "+moved\n"
    )

    result = apply_patch(tmp_path, diff, allow_delete=True)

    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_bytes() == b"moved\n"
    assert set(result.preimage) == {"old.txt", "new.txt"}
    assert set(result.postimage) == {"old.txt", "new.txt"}
    assert result.preimage["old.txt"]["exists"] is True
    assert result.postimage["old.txt"]["exists"] is False
    assert result.preimage["new.txt"]["exists"] is False
    assert result.postimage["new.txt"]["exists"] is True
