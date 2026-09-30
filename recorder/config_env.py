"""Parse ~/.config/flightrecorder/.env by hand (stdlib only). Never log values."""

from __future__ import annotations

from pathlib import Path

CREDENTIALS_PATH: Path = Path.home() / ".config" / "flightrecorder" / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Blank lines and # comments are skipped."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    text: str = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line: str = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key: str
        value: str
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def neo4j_settings(path: Path | None = None) -> tuple[str, str, str] | None:
    """Return (uri, username, password) or None if incomplete."""
    env: dict[str, str] = parse_env_file(path if path is not None else CREDENTIALS_PATH)
    uri: str = env.get("NEO4J_URI", "").strip()
    user: str = env.get("NEO4J_USERNAME", "").strip()
    password: str = env.get("NEO4J_PASSWORD", "").strip()
    if not uri or not user or not password:
        return None
    return uri, user, password
