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

## Command cleaning

Before a shell command is stored, `recorder.clean.clean_command` strips secrets
(headers, env assigns, URL userinfo/query, non-project paths). Use
`command_for_storage` so the toggle applies.

- **Default: on** (`CLEAN_COMMANDS=1`).
- **Off:** start the server with `CLEAN_COMMANDS=0` (or `false` / `off`), or set
  that key in `~/.config/flightrecorder/.env` once the server loads it.
- Turning cleaning **off** can put secrets into Neo4j later — debugging only.

Tests: `tests/test_clean.py`.

## Neo4j (background store)

Steps are saved **after** the hook answer, on a bounded queue (never slows
allow/deny). Credentials: `~/.config/flightrecorder/.env` (mode 600).

```bash
uv run python -m recorder.check_db          # prints connected
uv run python -m recorder.store --counts    # nodes + link types
uv run python -m recorder.store --clear     # only DELETE path
```

**TLS note (this laptop):** if `neo4j+s://…` fails with `ServiceUnavailable`
or `SSLCertVerificationError` while DNS/TCP still work, set
`NEO4J_URI=neo4j+ssc://…` (same host). Username may be the Aura instance id,
not always `neo4j`. Restart uvicorn after editing the env file.

If Neo4j is missing or down, the server still answers; writes are skipped with
a warning. Live Neo4j tests are skipped when the DB is unreachable so Check
stays offline-green.

## Live graph page

Open `http://127.0.0.1:8787/` (Host gate only; **no token**). The page polls
`GET /api/steps` every ~1s and draws the **in-memory** copy of cleaned steps
(not Neo4j). After `fake_agent.py` or a real Cursor session, you should see
steps left-to-right, `.env` amber, and a blocked curl with a dashed arrow to
**R1**.

```bash
uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787
# then open http://127.0.0.1:8787/
# offline UI check without server: open web/index.html?mock=1 from disk
```

**Auth split (SPEC §10):** `POST /hook` needs `X-Recorder-Token`. `GET /` and
`GET /api/steps` need only Host `127.0.0.1:8787` or `localhost:8787` (wrong
Host → 403). Restart uvicorn after pulling code that adds these routes.

**`GET /api/steps` contract** (last 10 of the most recent session; `?all=1` for
the full in-memory list):

```json
{
  "session": "abc",
  "steps": [
    {
      "order": 1,
      "kind": "read",
      "verdict": "allowed",
      "tool": null,
      "file": "README.md",
      "sensitive": false,
      "command": null,
      "host": null,
      "rule": null
    }
  ]
}
```

Empty: `{"session": null, "steps": []}`. Fields are cleaned facts only — never
file contents or raw secrets.

