"""`agentfly wipe`: empty the local history now (D14).

Only the SQLite history goes. Session marks (sessions.json), subagent links (links.json) and
Neo4j are left alone, so a marked session still blocks R1 afterwards.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from agentfly.recorder.localstore import DB_NAME, WipeIncomplete, wipe_file
from agentfly.recorder.paths import data_dir


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("wipe", help="delete all saved session history from this Mac")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask first")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    path = data_dir() / DB_NAME
    if not path.is_file():
        print("agentfly wipe: no history to delete")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "agentfly wipe: not a terminal; pass --yes to delete without asking",
                file=sys.stderr,
            )
            return 2
        if input("Delete all saved session history? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("agentfly wipe: nothing deleted")
            return 1
    try:
        sessions, steps = wipe_file(path)
    except WipeIncomplete as exc:
        print(f"agentfly wipe: rows deleted, but {exc}; run it again", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError) as exc:
        print(
            f"agentfly wipe: failed ({type(exc).__name__}); nothing else was changed",
            file=sys.stderr,
        )
        return 1
    print(f"agentfly wipe: deleted {sessions} sessions and {steps} steps")
    print("Session marks, subagent links and Neo4j were not changed.")
    return 0
