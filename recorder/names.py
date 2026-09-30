"""Pure helpers for sensitive file names and local hosts."""

from __future__ import annotations

import ipaddress
import shlex
from pathlib import Path
from urllib.parse import urlparse

_ENV_SAFE_SUFFIXES = (".example", ".sample", ".template")


def is_sensitive(path: str) -> bool:
    """Return True if the file name alone looks like a secret-bearing file."""
    name = Path(path).name
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
    """Return the hostname from a URL, or None if missing."""
    return urlparse(url).hostname


def is_local_host(host: str) -> bool:
    """Return True for loopback and RFC1918 private addresses."""
    if host.lower() == "localhost" or host == "::1":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private)


def words(cmd: str) -> list[str]:
    """Split a shell command into words; fall back if shlex fails."""
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()
