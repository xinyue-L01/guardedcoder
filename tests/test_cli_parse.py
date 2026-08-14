from __future__ import annotations

from pathlib import Path

import pytest

from guardedcoder.cli import main, parse_args


COMMANDS = (
    "run",
    "approve",
    "reject",
    "resume",
    "apply",
    "discard",
    "auth",
    "config",
    "memory",
)


def _fake_key() -> str:
    return "sk" + "-test"


def _argv_for(command: str) -> list[str]:
    if command in {"approve", "reject"}:
        return [command, "task-1", "fp-1"]
    return [command]


def test_pyproject_registers_guardedcoder_console_script() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "[project.scripts]" in text
    assert 'guardedcoder = "guardedcoder.cli:main"' in text


def test_cli_uses_argparse_not_click_or_typer() -> None:
    import guardedcoder.cli as cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "import argparse" in src
    assert "click" not in src.lower()
    assert "typer" not in src.lower()


def test_cli_module_does_not_import_keyring_or_httpx() -> None:
    import guardedcoder.cli as cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "keyring" not in src
    assert "httpx" not in src


@pytest.mark.parametrize("command", COMMANDS)
def test_known_command_parses_and_dispatches(command: str) -> None:
    seen: list[object] = []

    def fake_dispatcher(args: object) -> int:
        seen.append(args)
        return 0

    code = main(_argv_for(command), dispatcher=fake_dispatcher)
    assert code == 0
    assert len(seen) == 1
    assert getattr(seen[0], "command") == command


def test_unknown_command_is_nonzero_and_does_not_dispatch() -> None:
    seen: list[object] = []

    def fake_dispatcher(args: object) -> int:
        seen.append(args)
        return 0

    code = main(["not-a-command"], dispatcher=fake_dispatcher)
    assert code != 0
    assert seen == []


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_approve_and_reject_require_task_id_and_fingerprint(command: str) -> None:
    seen: list[object] = []

    def fake_dispatcher(args: object) -> int:
        seen.append(args)
        return 0

    assert main([command], dispatcher=fake_dispatcher) != 0
    assert main([command, "task-1"], dispatcher=fake_dispatcher) != 0
    assert seen == []

    code = main([command, "task-1", "fp-1"], dispatcher=fake_dispatcher)
    assert code == 0
    assert len(seen) == 1
    assert getattr(seen[0], "task_id") == "task-1"
    assert getattr(seen[0], "fingerprint") == "fp-1"


def test_parse_args_does_not_invoke_dispatcher() -> None:
    ns = parse_args(["run"])
    assert ns.command == "run"


def test_parse_approve_exposes_both_positionals() -> None:
    ns = parse_args(["approve", "task-9", "deadbeef"])
    assert ns.command == "approve"
    assert ns.task_id == "task-9"
    assert ns.fingerprint == "deadbeef"


def test_default_dispatch_is_noop() -> None:
    assert main(["run"]) == 0
    assert main(["memory"]) == 0


def test_unknown_command_error_redacts_fake_key(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _fake_key()
    code = main([fake])
    err = capsys.readouterr().err
    assert code != 0
    assert fake not in err
    assert "[redacted]" in err


def test_dispatcher_exception_is_redacted_and_assertable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _fake_key()

    def boom(_args: object) -> int:
        raise RuntimeError("provider failed with " + fake)

    code = main(["run"], dispatcher=boom)
    err = capsys.readouterr().err
    assert code != 0
    assert fake not in err
    assert "[redacted]" in err
    assert "provider failed with" in err
