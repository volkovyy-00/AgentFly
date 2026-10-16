"""`agentfly serve`: run the recorder in the foreground on 127.0.0.1."""

from __future__ import annotations

import argparse
import errno
import logging
import os
import socket
import sys
from collections.abc import Mapping

from agentfly.recorder import DEFAULT_PORT

PORT_ENV: str = "AGENTFLY_PORT"


def parse_port(text: str, lowest: int) -> int:
    """A port number from `lowest` to 65535, or ValueError."""
    if not text.isdecimal() or not lowest <= int(text) <= 65535:
        raise ValueError(f"must be a port number from {lowest} to 65535")
    return int(text)


def port_option(text: str) -> int:
    """argparse type for --port (0 asks the system for a free port)."""
    try:
        return parse_port(text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def resolve_port(option: int | None, env: Mapping[str, str]) -> int:
    """`--port` wins, then AGENTFLY_PORT, then 8787. Only `serve` reads the variable (D25)."""
    if option is not None:
        return option
    raw: str = env.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return parse_port(raw, 1)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV} {exc}") from None


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("serve", help="run the recorder in the foreground")
    parser.add_argument(
        "--port",
        type=port_option,
        default=None,
        help=f"port on 127.0.0.1 (default: ${PORT_ENV}, else {DEFAULT_PORT})",
    )
    parser.set_defaults(run=run)


def bind_port(port: int) -> socket.socket:
    """Take the port and start listening, or raise OSError.

    This runs before the app starts: uvicorn opens its own socket only after the app's startup,
    which writes the token, so a second `serve` would rewrite the first one's token and then fail.
    The socket is handed to uvicorn, so nothing can take the port in between. It listens at once:
    two sockets that are only bound can share a port on some systems.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))  # 127.0.0.1 only (SPEC section 3): there is no --host
        sock.listen(2048)
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


def run(args: argparse.Namespace) -> int:
    try:
        port: int = resolve_port(args.port, os.environ)
    except ValueError as exc:
        print(f"agentfly serve: {exc}", file=sys.stderr)
        return 2

    try:
        sock = bind_port(port)
    except OSError as exc:
        why = (
            "is already in use (is another recorder running?)"
            if exc.errno == errno.EADDRINUSE
            else f"cannot be used ({exc.strerror})"
        )
        print(f"agentfly serve: port {port} {why}; nothing was changed", file=sys.stderr)
        return 1

    import uvicorn

    from agentfly.recorder import app as recorder_app

    config = uvicorn.Config(recorder_app.app, host="127.0.0.1", port=port, log_level="info")
    # uvicorn prints its "running on" line only when it opens the socket itself.
    logging.getLogger("uvicorn.error").info(
        "Uvicorn running on http://127.0.0.1:%d (Press CTRL+C to quit)", sock.getsockname()[1]
    )
    uvicorn.Server(config).run(sockets=[sock])
    return 0
