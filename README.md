# Flight Recorder

Cursor hooks send every agent action to a local server that decides allow/block,
saves a cleaned copy to Neo4j, and draws the session as a live graph.

See `SPEC.md` (source of truth), `AGENTS.md` (working rules), and `HOOKS.md`
(hook wiring). Real Neo4j credentials live in `~/.config/flightrecorder/.env`,
never in this repo.

## Setup

```bash
uv sync
./install.sh
```

Check (run before reporting a step done):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Server (later): `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`
