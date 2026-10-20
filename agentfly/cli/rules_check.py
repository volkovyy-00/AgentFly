"""`agentfly rules check [FILE]`: is the rules file well formed? Exit 1 and name the rule if not."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentfly.recorder import rulefile


def add_file_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        metavar="FILE",
        help="a rules file (default: the active file if there is one, else the packaged default)",
    )


def choose_file(given: Path | None) -> tuple[Path, str]:
    """The file to read and a few words on where it came from."""
    if given is not None:
        return given, "file given"
    path, active = rulefile.in_force_path()
    return path, "the active file" if active else "the packaged default; there is no active file"


def load(command: str, path: Path) -> rulefile.RuleFile | None:
    """Read the file; print every problem to stderr and return None if it has any.

    The active file is read as the recorder reads it, who owns it included, so this never says
    "ok" for a file the recorder would refuse. Any other file is a draft: it is the user's own.
    """
    loaded: rulefile.RuleFile = (
        rulefile.load_active_file(path)
        if rulefile.is_active_path(path)
        else rulefile.load_file(path)
    )
    if loaded.errors:
        for error in loaded.errors:
            print(f"agentfly rules {command}: {path}: {error}", file=sys.stderr)
        return None
    return loaded


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "check",
        help="check a rules file: schema, unknown fields, R0, patterns that match everything",
        description=(
            "Exit 0 if the file would be used, 1 if not (every problem is printed and names its "
            "rule). Lines starting with 'warn:' are advice and do not change the exit code."
        ),
    )
    add_file_argument(parser)
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    path, what = choose_file(args.file)
    loaded = load("check", path)
    if loaded is None:
        return 1
    count = rulefile.rules_word(len(loaded.rules))
    print(f"ok: {count} in {path} ({what}), plus R0, which is built in")
    for line in loaded.lint:
        print(f"warn: {line}")
    return 0
