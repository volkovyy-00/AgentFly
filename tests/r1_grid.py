"""The sample grid D27 was once judged on (V5b-fix), kept as a second opinion (V5b-fix2 §6.4).

`rulefile` now judges R1's `after` by the shape of its patterns (`rulefile.covers`). These are the
names SPEC section 5 counts as secrets, in the shapes a list is likely to get wrong, and
`unmarked` says which of them (in several places, and as a shell word) an `after` clause does not
fire on: for a file the structural rule accepts it must be none.
"""

from __future__ import annotations

import string
from typing import Any

from agentfly.recorder import rulefile

_FAMILIES: tuple[str, ...] = (".env", "x.pem", ".pem", "k.key", ".key", "id_rsa", "credentials")
_TAILS: tuple[str, ...] = (
    "",
    ".local",
    ".production",
    ".1",
    "-w",
    "_w",
    "~",
    ".x.y",
    ".bak",
    ".test",
    ".dist",
    ".yml",
    ".md",
    ".example",
    ".sample",
    ".template",
    ".pub",
)
_SWEEP: str = string.ascii_letters + string.digits + "_-~.@+,%é"
_LITERALS: tuple[str, ...] = (
    "prod.pem",
    "server.key",
    ".env.staging",
    "credentials.json",
    "id_rsa2",
    ".env._x",
    ".env.example.local",
)
_FOLDERS: tuple[str, ...] = ("", "cfg/", "a/b/", "/Users/me/proj/", "~/")


def _secret_names() -> tuple[str, ...]:
    """Names SPEC section 5 counts as secrets, in the shapes a list is likely to get wrong: every
    family with every kind of tail, one character after each stem, and a few whole names."""
    names: set[str] = {family + tail for family in _FAMILIES for tail in _TAILS}
    for stem in (".env.", "id_rsa", "credentials"):
        names |= {stem + char for char in _SWEEP}
    for char in _SWEEP:
        names |= {char + ".pem", char + ".key", f".env.{char}x"}
    names |= set(_LITERALS)
    return tuple(sorted(name for name in names if rulefile.spec_secret(name)))


SECRET_NAMES: tuple[str, ...] = _secret_names()


def _read_of(path: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeReadFile", "file_path": path}


def unmarked(after: rulefile.Clause) -> tuple[str, ...]:
    """Secret names (in several places) that R1's `after` clause does not fire on."""
    left: list[str] = []
    for name in SECRET_NAMES:
        forms: list[str] = [folder + name for folder in _FOLDERS]
        forms += [name.upper(), "cfg/" + name.upper()]
        if any(not after.matches(_read_of(form), {}) for form in forms):
            left.append(name)
    for name in SECRET_NAMES[:: max(len(SECRET_NAMES) // 12, 1)]:  # a shell word counts too
        word: dict[str, Any] = {"hook_event_name": "beforeShellExecution", "command": f"cat {name}"}
        if name not in left and not after.matches(word, {}):
            left.append(name)
    return tuple(left)
