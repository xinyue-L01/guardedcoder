from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from guardedcoder.security.redact import redact_text

Dispatcher = Callable[[argparse.Namespace], int]

_COMMANDS = (
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
_TWO_POSITIONALS = frozenset({"approve", "reject", "resume"})
_CONFIG_COMMANDS = ("init", "validate", "show")
_AUTH_COMMANDS = ("set", "status", "update", "clear")


def _sanitize_argparse_message(message: str) -> str:
    if "unrecognized arguments:" in message:
        return "unrecognized arguments: [redacted]"
    return redact_text(message)


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(
            redact_text(f"{self.prog}: error: {_sanitize_argparse_message(message)}"),
            file=sys.stderr,
        )
        raise SystemExit(2)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            print(redact_text(_sanitize_argparse_message(message)), file=sys.stderr)
        raise SystemExit(status)


def _add_harness_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--harness-dir")


def build_parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(prog="guardedcoder")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        cmd = sub.add_parser(name)
        if name == "config":
            cfg = cmd.add_subparsers(dest="config_command", required=True)
            for action in _CONFIG_COMMANDS:
                cfg.add_parser(action)
        elif name == "auth":
            auth = cmd.add_subparsers(dest="auth_command", required=True)
            for action in _AUTH_COMMANDS:
                auth.add_parser(action)
        elif name == "memory":
            mem = cmd.add_subparsers(dest="memory_command", required=True)
            add = mem.add_parser("add")
            add.add_argument("--repo-id", required=True)
            add.add_argument("--type", required=True)
            add.add_argument("--content", required=True)
            add.add_argument("--rationale")
            add.add_argument("--path", action="append", default=[])
            add.add_argument("--tag", action="append", default=[])
            _add_harness_dir(add)
            for action in ("list", "export", "clear"):
                item = mem.add_parser(action)
                item.add_argument("--repo-id", required=True)
                _add_harness_dir(item)
        elif name in _TWO_POSITIONALS:
            cmd.add_argument("task_id")
            cmd.add_argument("fingerprint")
            _add_harness_dir(cmd)
        elif name == "apply":
            cmd.add_argument("task_id")
            cmd.add_argument("--confirm", action="store_true")
            _add_harness_dir(cmd)
        elif name == "discard":
            cmd.add_argument("task_id")
            _add_harness_dir(cmd)
        elif name == "run":
            cmd.add_argument("--repo")
            cmd.add_argument("--task", default="")
            cmd.add_argument("--confirm-envelope-hash")
            cmd.add_argument("--config")
            cmd.add_argument("--max-steps", type=int)
            _add_harness_dir(cmd)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = None if argv is None else list(argv)
    return build_parser().parse_args(args)


def default_dispatch(
    args: argparse.Namespace,
    *,
    getpass_fn: Callable[..., str] | None = None,
    key_store: object | None = None,
    config_path: Path | None = None,
    llm: object | None = None,
    harness_dir: Path | str | None = None,
) -> int:
    if args.command == "config":
        from guardedcoder.config.commands import handle_config

        return handle_config(args, config_path=config_path)
    if args.command == "auth":
        from guardedcoder.auth.commands import handle_auth

        return handle_auth(
            args,
            getpass_fn=getpass_fn,
            key_store=key_store,
            config_path=config_path,
        )
    from guardedcoder.loop.service import handle_command

    return handle_command(
        args,
        getpass_fn=getpass_fn,
        key_store=key_store,
        config_path=config_path,
        llm=llm,
        harness_dir=harness_dir,
    )


def dispatch(_args: argparse.Namespace) -> int:
    return default_dispatch(_args)


def main(
    argv: Sequence[str] | None = None,
    dispatcher: Dispatcher | None = None,
    *,
    getpass_fn: Callable[..., str] | None = None,
    key_store: object | None = None,
    config_path: Path | None = None,
    llm: object | None = None,
    harness_dir: Path | str | None = None,
) -> int:
    handler = dispatcher
    if handler is None:

        def handler(parsed: argparse.Namespace) -> int:
            return default_dispatch(
                parsed,
                getpass_fn=getpass_fn,
                key_store=key_store,
                config_path=config_path,
                llm=llm,
                harness_dir=harness_dir,
            )

    try:
        parsed = parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(redact_text(str(code)), file=sys.stderr)
        return 1
    try:
        result = handler(parsed)
    except Exception as exc:
        print(redact_text(str(exc)), file=sys.stderr)
        return 1
    if result is None:
        return 0
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
