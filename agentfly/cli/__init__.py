"""The `agentfly` command: one module per subcommand, dispatched with argparse."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agentfly.cli import init, serve, uninstall, wipe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentfly", description="AgentFly for AI coding agents")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    serve.add_parser(commands)
    wipe.add_parser(commands)
    init.add_parser(commands)
    uninstall.add_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace = build_parser().parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
