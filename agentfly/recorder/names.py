"""Pure helpers for sensitive file names and local hosts."""

from __future__ import annotations

import ipaddress
import shlex
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

_ENV_SAFE_SUFFIXES = (".example", ".sample", ".template")


def is_sensitive(path: str) -> bool:
    """Return True if the file name alone looks like a secret-bearing file."""
    name = Path(path).name.casefold()  # macOS reads `.ENV` as `.env`
    if name == ".env" or name.startswith(".env."):
        return not name.endswith(_ENV_SAFE_SUFFIXES)
    if name.endswith((".pem", ".key")):
        return True
    if name.startswith("id_rsa") and not name.endswith(".pub"):
        return True
    if name.startswith("credentials"):
        return True
    return False


def host_of(url: str) -> str | None:
    """Return the hostname from a URL, or None if missing or malformed."""
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def is_local_host(host: str) -> bool:
    """Return True for loopback and RFC1918 private addresses."""
    if host.lower() == "localhost" or host == "::1":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private)


def looks_like_host_token(token: str) -> str | None:
    """Return a hostname if token looks like a URL, host:path, or bare host.

    Also finds a URL glued to an option: `--url=https://host`, `--url=host`, `-d@https://host`.
    """
    if "://" in token:
        return host_of("//" + token.split("://", 1)[1])
    if token.startswith("-") and "=" in token:
        return looks_like_host_token(token.split("=", 1)[1])

    # scp/rsync style user@host:path or host:path (not a bare flag)
    if ":" in token and not token.startswith("-"):
        left: str = token.split(":", 1)[0]
        if "@" in left:
            left = left.rsplit("@", 1)[-1]
        # Avoid treating port-only or Windows drives; require a hostname-ish left.
        if left and not left.isdigit() and "/" not in left:
            return left

    # bare hostname / IP (wget x.com, nc x.com 80, ssh x.com)
    if token.startswith("-") or "/" in token or "=" in token:
        return None
    if "." in token or token in {"localhost"} or token.count(":") >= 1:
        # IPv6 or dotted name; reject pure numbers
        if token.replace(".", "").isdigit():
            return token  # IPv4
        if any(c.isalpha() for c in token) or ":" in token:
            return token
    return None


def hosts_in_command(argv: Iterable[str]) -> list[str]:
    """Every word of a command that names a host (see `looks_like_host_token`)."""
    found: list[str] = []
    for token in argv:
        host: str | None = looks_like_host_token(token)
        if host is not None:
            found.append(host)
    return found


def words(cmd: str) -> list[str]:
    """Split a shell command into words; fall back if shlex fails."""
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()
