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

`./install.sh` writes `.cursor/hooks.json` (the whole `.cursor/` tree is
gitignored). Run it after every clone and whenever `install.sh` changes.
Hook details and Checkpoint A notes: `HOOKS.md`, `demo/NOTES.md`.

Check (run before reporting a step done):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Server: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`

Replay without Cursor (server must be running for R1 blocks):

```bash
uv run python fake_agent.py
```

See `HOOKS.md` for architecture, R1, and `fake_agent` flags. Checkpoint A notes:
`demo/NOTES.md`.
