"""Verify Neo4j connectivity. Never prints the password."""

from __future__ import annotations

import logging
import sys

from neo4j import GraphDatabase

from recorder.config_env import CREDENTIALS_PATH, neo4j_settings


def main() -> int:
    # Keep driver chatter off the acceptance printout.
    logging.getLogger("neo4j").setLevel(logging.CRITICAL)
    settings: tuple[str, str, str] | None = neo4j_settings(CREDENTIALS_PATH)
    if settings is None:
        print("FileNotFoundError")
        return 1
    uri: str
    user: str
    password: str
    uri, user, password = settings
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001 — print class name only
        print(type(exc).__name__)
        return 1
    print("connected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
