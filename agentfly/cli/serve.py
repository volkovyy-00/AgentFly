"""`agentfly serve`: run the recorder in the foreground on 127.0.0.1."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from collections.abc import Mapping

from agentfly.recorder import DEFAULT_PORT

PORT_ENV: str = "AGENTFLY_PORT"


def resolve_port(option: int | None, env: Mapping[str, str]) -> int:
    """`--port` wins, then AGENTFLY_PORT, then 8787. Only `serve` reads the variable (D25)."""
    if option is not None:
        return option
    raw: str = env.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    if not raw.isdecimal() or not 1 <= int(raw) <= 65535:
        raise ValueError(f"{PORT_ENV} must be a port number from 1 to 65535")
    return int(raw)


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("serve", help="run the recorder in the foreground")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port on 127.0.0.1 (default: ${PORT_ENV}, else {DEFAULT_PORT})",
    )
    parser.set_defaults(run=run)


def bind_port(port: int) -> socket.socket | None:
    """Take the port, or return None if something already has it.

    This runs before the app starts: uvicorn opens its own socket only after the app's startup,
    which writes the token, so a second `serve` would rewrite the first one's token and then fail.
    The socket is handed to uvicorn, so nothing can take the port in between.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))  # 127.0.0.1 only (SPEC section 3): there is no --host
    except OSError:
        sock.close()
        return None
    sock.set_inheritable(True)
    return sock


def run(args: argparse.Namespace) -> int:
    try:
        port: int = resolve_port(args.port, os.environ)
    except ValueError as exc:
        print(f"agentfly serve: {exc}", file=sys.stderr)
        return 2

    sock = bind_port(port)
    if sock is None:
        print(
            f"agentfly serve: port {port} is already in use (is another recorder running?); "
            "nothing was changed",
            file=sys.stderr,
        )
        return 1

    import uvicorn

    from agentfly.recorder import app as recorder_app

    config = uvicorn.Config(recorder_app.app, host="127.0.0.1", port=port, log_level="info")
    uvicorn.Server(config).run(sockets=[sock])
    return 0
