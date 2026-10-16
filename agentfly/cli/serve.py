"""`agentfly serve`: run the recorder in the foreground on 127.0.0.1."""

from __future__ import annotations

import argparse

from agentfly.recorder import DEFAULT_PORT


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("serve", help="run the recorder in the foreground")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port on 127.0.0.1 (default {DEFAULT_PORT})",
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    import uvicorn

    from agentfly.recorder import app as recorder_app

    # 127.0.0.1 only (SPEC section 3): there is deliberately no --host option.
    uvicorn.run(recorder_app.app, host="127.0.0.1", port=args.port, log_level="info")
    return 0
