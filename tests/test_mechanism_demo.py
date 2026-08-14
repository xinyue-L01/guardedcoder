from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demos" / "mechanism_demo.py"

_MAX_STDOUT_CHARS = 8192
_SECRET_RE = re.compile(
    r"sk-[A-Za-z0-9_-]+|-----BEGIN[ A-Z0-9]*PRIVATE KEY-----|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}"
)
_SCENE_ORDER = (
    "SCENE 1 governance",
    "SCENE 2 fail_loop",
    "SCENE 3 permit_window",
    "SCENE 4 illegal_toml",
)


def _run_demo() -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    src = str(ROOT / "src")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not previous else src + os.pathsep + previous
    return subprocess.run(
        [sys.executable, str(DEMO)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_demo_script_exists() -> None:
    assert DEMO.is_file()


def test_demo_exits_zero_with_four_scenes_in_order() -> None:
    result = _run_demo()
    assert result.returncode == 0
    stdout = result.stdout
    positions = [stdout.index(label) for label in _SCENE_ORDER]
    assert positions == sorted(positions)
    assert result.stderr == ""


def test_demo_repeat_runs_match() -> None:
    first = _run_demo()
    second = _run_demo()
    assert first.returncode == 0
    assert second.returncode == first.returncode
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr


def test_demo_output_is_bounded_and_has_no_secrets_or_full_diffs() -> None:
    result = _run_demo()
    assert result.returncode == 0
    blob = result.stdout + result.stderr
    assert len(blob) <= _MAX_STDOUT_CHARS
    assert _SECRET_RE.search(blob) is None
    assert "--- a/" not in blob
    assert "+++ b/" not in blob
    assert "def " not in blob
    lowered = blob.lower()
    assert "api_key" not in lowered
    assert "password" not in lowered


def test_governance_scene_rejects_schema_escape_sensitive_forbidden_and_hitl() -> None:
    result = _run_demo()
    assert result.returncode == 0
    text = result.stdout
    gov = _scene_block(text, "SCENE 1 governance", "SCENE 2 fail_loop")
    assert "unknown_action: schema_reject" in gov
    assert "workspace_escape: deny WORKSPACE_ESCAPE" in gov
    assert "sensitive_path: deny SENSITIVE_PATH" in gov
    assert "hard_forbidden: deny HARD_FORBIDDEN_COMMAND" in gov
    assert "in_tree_write_outside_range: hitl NeedApproval" in gov
    assert "network" not in gov.split(":", 1)[0]


def test_fail_loop_requires_structured_fail_before_correction() -> None:
    result = _run_demo()
    assert result.returncode == 0
    block = _scene_block(result.stdout, "SCENE 2 fail_loop", "SCENE 3 permit_window")
    assert "gate_on_fail: true" in block
    assert "before_fail: blocked no_correction_patch" in block
    assert "after_fail: correction_patch fingerprint_changed" in block
    assert "unconditional" not in block


def test_permit_window_refuses_replays_and_fail_closes_crash() -> None:
    result = _run_demo()
    assert result.returncode == 0
    block = _scene_block(
        result.stdout, "SCENE 3 permit_window", "SCENE 4 illegal_toml"
    )
    assert "wrong_fingerprint: refuse" in block
    assert "old_approval_replay: refuse" in block
    assert "permit_replay: refuse" in block
    assert (
        "happy_path: evaluate>create_permit>consume_open_window>execute>observation"
        in block
    )
    assert "crash_recovery_run_command: fail_closed recorded_error no_rerun" in block
    assert "crash_recovery_apply_patch: retryable_same_attempt" in block
    assert "crash_recovery_run_command:" in block
    assert "crash_recovery_apply_patch:" in block
    run_idx = block.index("crash_recovery_run_command:")
    patch_idx = block.index("crash_recovery_apply_patch:")
    assert block[run_idx : run_idx + 80] != block[patch_idx : patch_idx + 80]


def test_illegal_toml_refuses_without_worktree_or_llm() -> None:
    result = _run_demo()
    assert result.returncode == 0
    block = result.stdout.split("SCENE 4 illegal_toml", 1)[1]
    assert "unknown_key: refuse no_worktree no_llm" in block
    assert "secret_like: refuse no_worktree no_llm" in block
    assert "shell_string: refuse no_worktree no_llm" in block
    assert "hard_forbidden_profile: refuse no_worktree no_llm" in block
    assert "wrong_type: refuse no_worktree no_llm" in block
    assert "legal_synthesize: identical_envelope_hash" in block


def test_demo_source_does_not_add_network_push_or_publish_tools() -> None:
    source = DEMO.read_text(encoding="utf-8")
    assert "action\": \"network\"" not in source
    assert "action='network'" not in source
    assert "def network" not in source
    assert "class Network" not in source
    lowered = source.lower()
    assert "git push" not in lowered
    assert "twine publish" not in lowered
    assert "requests." not in lowered
    assert "urllib.request" not in lowered
    assert "httpx" not in lowered


def _scene_block(stdout: str, start: str, end: str) -> str:
    head, _, rest = stdout.partition(start)
    del head
    block, _, _tail = rest.partition(end)
    return start + block
