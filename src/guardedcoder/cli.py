from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

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
_TWO_POSITIONALS = frozenset({"approve", "reject"})


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(redact_text(f"{self.prog}: error: {message}"), file=sys.stderr)
        raise SystemExit(2)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            print(redact_text(message), file=sys.stderr)
        raise SystemExit(status)


def build_parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(prog="guardedcoder")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        cmd = sub.add_parser(name)
        if name in _TWO_POSITIONALS:
            cmd.add_argument("task_id")
            cmd.add_argument("fingerprint")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = None if argv is None else list(argv)
    return build_parser().parse_args(args)


def dispatch(_args: argparse.Namespace) -> int:
    return 0


def main(
    argv: Sequence[str] | None = None,
    dispatcher: Dispatcher | None = None,
) -> int:
    handler = dispatch if dispatcher is None else dispatcher
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
