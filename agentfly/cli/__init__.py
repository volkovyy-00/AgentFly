"""The `agentfly` command: one module per subcommand, dispatched with argparse."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agentfly.cli import doctor, init, serve, start, status, stop, uninstall, wipe
from agentfly.install import InstallError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentfly", description="AgentFly for AI coding agents")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    serve.add_parser(commands)
    wipe.add_parser(commands)
    init.add_parser(commands)
    uninstall.add_parser(commands)
    start.add_parser(commands)
    stop.add_parser(commands)
    status.add_parser(commands)
    doctor.add_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        return int(args.run(args))
    except (
        InstallError
    ) as exc:  # a refusal with a message the user can act on: one line, no traceback
        print(f"agentfly {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
