from pathlib import Path

from guardedcoder.governance.classify import classify_write
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.models.permit import Classification, RiskDecision


def _envelope(write_paths: tuple[str, ...] = ("src",)) -> Envelope:
    return Envelope(
        read_paths=("src",),
        write_paths=write_paths,
        profiles=(
            CommandProfile(
                profile_id="pytest",
                argv_template=["pytest", "--junitxml", "{junit_out}"],
                cwd=".",
                timeout_seconds=60,
                max_output_bytes=65536,
            ),
        ),
        verify_profiles=("pytest",),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def test_risk_decision_values() -> None:
    assert RiskDecision.Allow == "Allow"
    assert RiskDecision.NeedApproval == "NeedApproval"
    assert RiskDecision.Deny == "Deny"


def test_workspace_escape_is_deny(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    result = classify_write(tmp_path, _envelope(), "../secret")
    assert result.decision == RiskDecision.Deny
    assert result.code == "WORKSPACE_ESCAPE"


def test_sensitive_path_is_deny(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("x", encoding="utf-8")
    result = classify_write(tmp_path, _envelope(), ".env")
    assert result.decision == RiskDecision.Deny
    assert result.code == "SENSITIVE_PATH"


def test_sensitive_under_write_path_is_still_deny(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / ".env.local").write_text("x", encoding="utf-8")
    result = classify_write(tmp_path, _envelope(), "src/.env.local")
    assert result.decision == RiskDecision.Deny
    assert result.code == "SENSITIVE_PATH"


def test_in_tree_outside_write_paths_is_need_approval(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("x", encoding="utf-8")
    result = classify_write(tmp_path, _envelope(("src",)), "docs/note.md")
    assert result.decision == RiskDecision.NeedApproval
    assert result.code is None


def test_under_write_path_is_allow(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("print(1)\n", encoding="utf-8")
    result = classify_write(tmp_path, _envelope(("src",)), "src/foo.py")
    assert result.decision == RiskDecision.Allow
    assert result.code is None


def test_write_path_prefix_does_not_match_sibling(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    src2 = tmp_path / "src2"
    src2.mkdir()
    (src2 / "foo.py").write_text("print(1)\n", encoding="utf-8")
    result = classify_write(tmp_path, _envelope(("src",)), "src2/foo.py")
    assert result.decision == RiskDecision.NeedApproval
    assert result.code is None


def test_classification_is_frozen() -> None:
    item = Classification(decision=RiskDecision.Allow, code=None)
    assert item.decision == RiskDecision.Allow
    try:
        item.decision = RiskDecision.Deny  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Classification must be frozen")
