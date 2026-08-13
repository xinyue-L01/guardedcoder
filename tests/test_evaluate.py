from pathlib import Path

from guardedcoder.governance.evaluate import Verdict, VerdictKind, evaluate
from guardedcoder.models.actions import (
    FinishAction,
    ListDirAction,
    ReadFileAction,
    RunCommandAction,
)
from guardedcoder.models.envelope import CommandProfile, Envelope
from guardedcoder.models.task import TaskBudget


def _envelope(
    write_paths: tuple[str, ...] = ("src",),
    *profiles: CommandProfile,
    read_paths: tuple[str, ...] = ("src",),
) -> Envelope:
    if not profiles:
        profiles = (
            CommandProfile(
                profile_id="pytest",
                argv_template=["pytest", "--junitxml", "{junit_out}"],
                cwd=".",
                timeout_seconds=60,
                max_output_bytes=65536,
            ),
        )
    return Envelope(
        read_paths=read_paths,
        write_paths=write_paths,
        profiles=profiles,
        verify_profiles=tuple(p.profile_id for p in profiles),
        max_steps=10,
        max_total_seconds=300,
        allow_delete=False,
        allow_network=False,
        config_digest="abc",
    )


def _read(path: str) -> ReadFileAction:
    return ReadFileAction(action="read_file", path=path)


def _list(path: str) -> ListDirAction:
    return ListDirAction(action="list_dir", path=path)


def _run(profile_id: str) -> RunCommandAction:
    return RunCommandAction(action="run_command", profile_id=profile_id)


def test_verdict_kind_values() -> None:
    assert set(VerdictKind) == {
        "Allow",
        "NeedApproval",
        "NeedEnvelopeRevision",
        "Deny",
    }


def test_verdict_and_budget_are_frozen() -> None:
    verdict = Verdict(kind=VerdictKind.Allow, code=None)
    budget = TaskBudget(remaining_steps=3)
    try:
        verdict.kind = VerdictKind.Deny  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Verdict must be frozen")
    try:
        budget.remaining_steps = 0  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TaskBudget must be frozen")


def test_unknown_profile_is_need_envelope_revision(tmp_path: Path) -> None:
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=_run("missing"),
        budget=TaskBudget(remaining_steps=10),
    )
    assert result.kind == VerdictKind.NeedEnvelopeRevision
    assert result.code == "COMMAND_NOT_ALLOWED"


def test_zero_budget_denies_otherwise_allow_read(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("print(1)\n", encoding="utf-8")
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=_read("src/foo.py"),
        budget=TaskBudget(remaining_steps=0),
    )
    assert result.kind == VerdictKind.Deny
    assert result.code == "BUDGET_EXHAUSTED"


def test_workspace_escape_not_upgraded_by_budget(tmp_path: Path) -> None:
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=_read("../secret"),
        budget=TaskBudget(remaining_steps=99),
    )
    assert result.kind == VerdictKind.Deny
    assert result.code == "WORKSPACE_ESCAPE"


def test_fence_deny_keeps_code_when_budget_exhausted(tmp_path: Path) -> None:
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=_read("../secret"),
        budget=TaskBudget(remaining_steps=0),
    )
    assert result.kind == VerdictKind.Deny
    assert result.code == "WORKSPACE_ESCAPE"


def test_hard_forbidden_profile_in_constructed_envelope(tmp_path: Path) -> None:
    env = _envelope(
        ("src",),
        CommandProfile(
            profile_id="pip_install",
            argv_template=["pip3", "install", "pkg"],
            cwd=".",
            timeout_seconds=60,
            max_output_bytes=65536,
        ),
    )
    result = evaluate(
        worktree=tmp_path,
        envelope=env,
        action=_run("pip_install"),
        budget=TaskBudget(remaining_steps=10),
    )
    assert result.kind == VerdictKind.Deny
    assert result.code == "HARD_FORBIDDEN_COMMAND"


def test_finish_with_remaining_steps_is_allow(tmp_path: Path) -> None:
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=FinishAction(action="finish", outcome="success"),
        budget=TaskBudget(remaining_steps=1),
    )
    assert result.kind == VerdictKind.Allow
    assert result.code is None


def test_read_outside_read_paths_is_deny_not_need_approval(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text("x", encoding="utf-8")
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(),
        action=_read("docs/note.md"),
        budget=TaskBudget(remaining_steps=5),
    )
    assert result.kind == VerdictKind.Deny
    assert result.kind != VerdictKind.NeedApproval
    assert result.kind != VerdictKind.Allow


def test_read_file_under_read_paths_is_allow(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(write_paths=("src",), read_paths=("docs",)),
        action=_read("docs/a.md"),
        budget=TaskBudget(remaining_steps=5),
    )
    assert result.kind == VerdictKind.Allow
    assert result.code is None


def test_read_file_under_write_paths_only_is_not_allow(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(write_paths=("src",), read_paths=("docs",)),
        action=_read("src/a.py"),
        budget=TaskBudget(remaining_steps=5),
    )
    assert result.kind != VerdictKind.Allow
    assert result.kind != VerdictKind.NeedApproval


def test_list_dir_under_write_paths_only_is_not_allow(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    result = evaluate(
        worktree=tmp_path,
        envelope=_envelope(write_paths=("src",), read_paths=("docs",)),
        action=_list("src"),
        budget=TaskBudget(remaining_steps=5),
    )
    assert result.kind != VerdictKind.Allow
    assert result.kind != VerdictKind.NeedApproval
