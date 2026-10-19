"""The Python package `init -g` and `uninstall` run as root, checked before the password prompt.

Those two commands re-run AgentFly's own code under `sudo`, and the code sits in a tool
environment the agent's user can write. So every file of every installed distribution is hashed
first. Against what depends on the distribution's version:

- the version equals the one in the root-owned record: each file must equal the hash stored then;
- the version differs, or the distribution is new (an upgrade): each file must equal the hash in
  the distribution's own `RECORD`, and the change is listed for the owner to confirm;
- there is no record yet (a first install, or one from before V3c): each file against its `RECORD`.

A file in `site-packages` that no `RECORD` lists is a mismatch too. The base Python (uv's or
Homebrew's, which other projects use) is never read. SPEC section 10 says what stays unchecked.

The environment is found from where `agentfly` was imported, never from `sysconfig` or
`sys.prefix`: root runs `python -I -S`, and on Homebrew's Python `-S` makes both name the base
Python.
"""

from __future__ import annotations

import base64
import binascii
import csv
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PathDistribution
from pathlib import Path
from typing import Any

import agentfly
from agentfly.install import InstallError
from agentfly.install.layout import SYSTEM
from agentfly.install.pythons import file_sha256

WHEEL_HINT = "uv build && uv tool install dist/*.whl"
# Files the tools that build environments leave in `site-packages` without listing them in a
# RECORD. Root runs `-S`, so it never reads a `.pth`; the owner's user may.
UNLISTED_OK: frozenset[str] = frozenset(
    {"_virtualenv.py", "_virtualenv.pth", "pipx_shared.pth", "homebrew_deps.pth"}
)


@dataclass(frozen=True)
class Environment:
    prefix: Path  # the virtual environment's root (the folder with pyvenv.cfg)
    site: Path  # its site-packages


@dataclass(frozen=True)
class Distribution:
    name: str  # PEP 503 normalised
    version: str
    files: dict[str, str]  # path as RECORD writes it (relative to site) -> SHA-256 hex


@dataclass(frozen=True)
class Check:
    distributions: dict[str, Distribution]  # what is on disk now: what the record should hold
    problems: list[str]  # a changed or extra file; empty when nothing is wrong
    changes: list[str]  # versions that differ from the record: the owner confirms these
    rebuilt: tuple[
        str, ...
    ]  # distributions with a problem though their version is the recorded one
    extra: bool  # a problem is a file that should not be there: installing over it keeps it


def lead(items: list[str]) -> str:
    """The first of `items`, and how many more there are."""
    return f"{items[0]} (and {len(items) - 1} more)" if len(items) > 1 else items[0]


@dataclass(frozen=True)
class _Found:
    name: str
    version: str
    actual: dict[str, str]  # readable regular files: path as listed -> SHA-256 hex
    recorded: dict[str, str | None]  # RECORD's sha256 per listed path as hex; None when unusable


# ---------------------------------------------------------------- the environment


def tool_environment() -> Environment:
    """Where this `agentfly` was imported from, if that is a wheel in a virtual environment."""
    site = Path(agentfly.__file__).parent.parent
    dists = (
        sorted(site.glob("agentfly_recorder-*.dist-info")) if site.name == "site-packages" else []
    )
    if not dists or any(_editable(dist) for dist in dists):
        raise InstallError(
            "AgentFly is running from a source checkout or an editable install, so it cannot be "
            f"checked before it runs as root. Install the wheel instead: {WHEEL_HINT}"
        )
    prefix = next((p for p in site.parents if (p / "pyvenv.cfg").is_file()), None)
    if prefix is None:
        raise InstallError(
            f"AgentFly is not installed in a virtual environment ({site}); install it with "
            "`uv tool install`, `pipx` or Homebrew"
        )
    return Environment(prefix, site)


def _editable(dist_info: Path) -> bool:
    try:
        data = json.loads((dist_info / "direct_url.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool((data.get("dir_info") or {}).get("editable"))


# ---------------------------------------------------------------- reading the environment


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _sha256_hex(recorded: str) -> str | None:
    """`sha256=<urlsafe base64>` as hex; None for another algorithm, no hash or bad base64."""
    algorithm, _, digest = recorded.partition("=")
    if algorithm != "sha256" or not digest:
        return None
    try:
        return base64.urlsafe_b64decode(digest + "=" * (-len(digest) % 4)).hex()
    except (binascii.Error, ValueError):
        return None


def _path(env: Environment, rel: str) -> str:
    return os.path.normpath(os.path.join(env.site, rel))


def _inside(path: str, folder: Path) -> bool:
    return path == str(folder) or path.startswith(f"{folder}{os.sep}")


def _read_dist(
    env: Environment, info: Path, listed: set[str], problems: list[str]
) -> _Found | None:
    try:
        meta = PathDistribution(info).metadata
        name, version = _normal(meta["Name"]), meta["Version"]
        with (info / "RECORD").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
    except (OSError, KeyError, ValueError, TypeError, csv.Error):
        problems.append(f"{info} has no readable METADATA and RECORD")
        return None
    own_record = os.path.normpath(info / "RECORD")
    listed.add(own_record)
    actual: dict[str, str] = {}
    recorded: dict[str, str | None] = {}
    for row in rows:
        if not row:
            continue
        rel = row[0]
        full = _path(env, rel)
        if full == own_record or "__pycache__" in rel.split("/"):
            continue  # RECORD cannot hash itself; byte-code is never read by root
        listed.add(full)
        recorded[rel] = _sha256_hex(row[1]) if len(row) > 1 else None
        if not _inside(full, env.prefix):
            problems.append(f"{info.name}/RECORD names {rel}, outside the environment")
            continue
        try:
            if stat.S_ISREG(os.stat(full).st_mode):
                actual[rel] = file_sha256(Path(full))
            else:
                problems.append(f"{full} is listed in RECORD but is not a regular file")
        except (OSError, ValueError) as exc:  # ValueError: a NUL byte in the path
            reason, shown = (
                (exc.strerror, full) if isinstance(exc, OSError) else (str(exc), repr(full))
            )
            problems.append(f"{shown} is listed in RECORD but cannot be read ({reason})")
    return _Found(name, version, actual, recorded)


def _unlisted(env: Environment, listed: set[str]) -> tuple[list[str], list[str]]:
    """Files under `site-packages` that no RECORD lists, and folders that cannot be listed.

    A link is a file, and is not followed. A folder the user cannot list is a finding: root can
    read what it holds (`neo4j` imports `numpy` if it finds one).
    """
    found: list[str] = []
    unlistable: list[str] = []
    top = os.path.normpath(env.site)

    def cannot_list(error: OSError) -> None:
        unlistable.append(f"{error.filename} cannot be listed ({error.strerror})")

    for root, dirs, files in os.walk(top, onerror=cannot_list):
        walk = []
        for folder in sorted(dirs):
            path = os.path.join(root, folder)
            if folder == "__pycache__":
                continue
            if os.path.islink(path):
                if path not in listed:
                    found.append(path)
            else:
                walk.append(folder)
        dirs[:] = walk
        for name in sorted(files):
            path = os.path.join(root, name)
            if (root == top and name in UNLISTED_OK) or path in listed:
                continue
            found.append(path)
    return found, unlistable


# ---------------------------------------------------------------- the record


def stored_from(record: dict[str, Any] | None) -> dict[str, tuple[str, dict[str, str]]] | None:
    """The `packages` section of `hashes.json` as name -> (version, files); None if it has none."""
    section = record.get("packages") if record else None
    if not isinstance(section, dict):
        return None
    stored: dict[str, tuple[str, dict[str, str]]] = {}
    for name, entry in section.items():
        files = entry.get("files") if isinstance(entry, dict) else None
        version = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(files, dict) or not isinstance(version, str):
            return None
        stored[name] = (version, {str(k): str(v) for k, v in files.items()})
    return stored


def to_record(distributions: dict[str, Distribution]) -> dict[str, Any]:
    return {
        name: {"version": dist.version, "files": dict(sorted(dist.files.items()))}
        for name, dist in sorted(distributions.items())
    }


# ---------------------------------------------------------------- the check


def inspect(env: Environment, record: dict[str, Any] | None) -> Check:
    """Hash the environment and compare it with `record` (the root-owned `hashes.json`)."""
    problems: list[str] = []
    listed: set[str] = set()
    found: dict[str, _Found] = {}
    for info in sorted(env.site.glob("*.dist-info")):
        dist = _read_dist(env, info, listed, problems)
        if dist is None:
            continue
        if dist.name in found:
            problems.append(f"{env.site} holds two copies of {dist.name}")
        found[dist.name] = dist
    unlisted, unlistable = _unlisted(env, listed)
    problems += [f"{path} is not listed in any RECORD" for path in unlisted]
    problems += [f"{why}, so what it holds cannot be checked" for why in unlistable]
    stored = stored_from(record)
    changes: list[str] = []
    rebuilt: list[str] = []
    extra = bool(unlisted or unlistable)
    for name, dist in sorted(found.items()):
        old = stored.get(name) if stored is not None else None
        if old is not None and old[0] == dist.version:
            mine, added = _against_stored(env, dist, old[1])
            rebuilt += [name] if mine else []
            extra = extra or added
        else:
            mine = _against_record(env, dist)
            if stored is not None:
                changes.append(
                    f"{name}: changed from {old[0] if old else 'none'} to {dist.version}"
                )
        problems += mine
    for name, (version, _files) in sorted((stored or {}).items()):
        if name not in found:
            changes.append(f"{name}: changed from {version} to none")
    distributions = {
        name: Distribution(name, dist.version, dict(dist.actual)) for name, dist in found.items()
    }
    return Check(distributions, problems, changes, tuple(rebuilt), extra)


def _against_stored(
    env: Environment, dist: _Found, files: dict[str, str]
) -> tuple[list[str], bool]:
    """Problems against the stored hashes, and whether one is a file that was not there then."""
    out: list[str] = []
    added = False
    for rel, digest in sorted(dist.actual.items()):
        if rel not in files:
            out.append(f"{_path(env, rel)} was not there when AgentFly was installed")
            added = True
        elif files[rel] != digest:
            out.append(f"{_path(env, rel)} changed since AgentFly was installed")
    # A stored file RECORD still lists but that could not be read was reported when it was read.
    for rel in sorted(set(files) - set(dist.recorded)):
        out.append(f"{_path(env, rel)} was there when AgentFly was installed and is gone")
    return out, added


def _against_record(env: Environment, dist: _Found) -> list[str]:
    out: list[str] = []
    for rel, digest in sorted(dist.actual.items()):
        wanted = dist.recorded.get(rel)
        if wanted is None:
            out.append(
                f"RECORD has no usable sha256 for {_path(env, rel)}, so it cannot be checked"
            )
        elif wanted != digest:
            out.append(f"{_path(env, rel)} does not match its RECORD")
    return out


def advice(check: Check) -> str:
    """How to get a clean environment back: one text for the refusal and for `doctor`."""
    reinstall = (
        "reinstall AgentFly from a source you trust (for example `uv tool install --force <wheel>`)"
    )
    if not check.extra:
        return reinstall
    return (  # with uv, installing over a file no RECORD lists leaves it in place (uv 0.9.5)
        "delete each extra file or uninstall AgentFly's package first (`uv tool uninstall "
        f"agentfly-recorder`; installing over it does not remove it), then {reinstall}"
    )


def require(record: dict[str, Any] | None, then: str) -> Check:
    """The check of this process's environment, or an InstallError that says how to recover."""
    check = inspect(tool_environment(), record)
    if check.problems:
        text = (
            f"AgentFly's package is not what was checked: {lead(check.problems)}. No password "
            f"was asked for and nothing was changed. To fix it, {advice(check)}, "
            f"and run `{then}` again."
        )
        if "agentfly-recorder" in check.rebuilt:
            text += (
                " If you rebuilt this version yourself, raise the version in pyproject.toml "
                "before you reinstall: a new version asks you to confirm instead of stopping."
            )
        if others := [name for name in check.rebuilt if name != "agentfly-recorder"]:
            text += (  # same version, other files: a reinstall under another Python does that
                f" {', '.join(others)} keep(s) the version recorded at install with other files, "
                "which reinstalling under another Python does, and a dependency's version cannot "
                f'be raised. To accept them, remove the record (`sudo rm "{SYSTEM.record}"`) and '
                f"run `{then}` again: with no record they are checked against their own RECORD "
                "files only, as on a first install."
            )
        raise InstallError(text)
    return check


def confirm(changes: list[str], ask: Callable[[str], str] | None = None) -> bool:
    """Show what changed since the record was made and ask the owner; only a terminal can answer."""
    print("AgentFly's package changed since the last `agentfly init -g`:")
    for line in changes:
        print(f"  {line}")
    print("Each file matches its own RECORD; a new version is trusted on that alone.")
    if ask is None:
        if sys.stdin is None or not sys.stdin.isatty():
            print("Run the command in a terminal to confirm this.", file=sys.stderr)
            return False
        ask = input
    try:
        answer = ask("Go on? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def ensure_confirmed(check: Check) -> None:
    """A version change since the record was made needs the owner's yes; no yes is a refusal."""
    if check.changes and not confirm(check.changes):
        raise InstallError("not confirmed; nothing was changed")
