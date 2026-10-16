# AGENTS.md — AgentFly

## What this project is
Cursor hooks send every agent action to a local server. The server decides
allow, warn or block using rules, and saves a cleaned copy to a local store
(Neo4j is an optional extra copy). A web page shows the session live. Read
`SPEC.md` first.

`SPEC.md` is the **v1 target**. The code is still the hackathon version and
moves toward it card by card. So:
- Inside your card, follow SPEC.md and the card.
- Outside your card, leave the code as it is and note the gap in your report.
- If SPEC.md and your card disagree, stop and ask. Do not silently pick one.

The hackathon spec is `docs/archive/SPEC-hackathon.md` (history only).

## Commands
These are today's commands; the packaging card (V2) changes them.
- Install deps: `uv sync`
- Wire Cursor hooks (writes gitignored `.cursor/hooks.json`): `./install.sh`
- Check (run before you report a step done): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
- Web check: `npm --prefix ui ci && npm --prefix ui run check`
- Stale-build check: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"`
- Auto-fix style: `uv run ruff check --fix . && uv run ruff format .`
- Run server: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`
- Replay a scripted session without Cursor: `uv run python fake_agent.py`
- UI dev server (proxies `/api` to the recorder): `npm --prefix ui run dev`

## Approved dependencies (no need to ask)
Python: fastapi, uvicorn, httpx, neo4j (driver), pytest, ruff, and hatchling
(build backend, D6). Standard-library `tomllib`, `sqlite3` and `argparse` need
no approval. The **bundled Python runtime** (D5) is also approved: a relocatable
standalone build (the kind uv downloads) that `agentfly init -g` installs for
the hook client; the packaging card picks the exact build. Ask before adding
anything else.

JavaScript (npm **only inside `ui/`**; commit `ui/dist`, ignore
`ui/node_modules` via `ui/.gitignore`): vite, react, react-dom, typescript,
tailwindcss, `@tailwindcss/vite`, vitest, `@vitejs/plugin-react`,
`@testing-library/react`, jsdom, `@types/node`, `@types/react`,
`@types/react-dom`, `@xyflow/react` and `motion` (the last two are pinned in
`ui/package.json`). The page at `/` is the Vite build in `ui/dist`.

## Working rules
- One card at a time. Do only the card you were asked for, then STOP and say
  what works and what does not. Do not start the next card. The card says what
  you may touch.
- The block decision uses in-memory state only. It never waits for a database
  or the network. Writes to the local store (and to Neo4j, when enabled) happen
  in the background and must never slow or break a hook response.
- Do not guess how Cursor hooks behave. Log the real input first (with file
  contents thrown away), then code against what actually arrives. After the
  logging stage, paste the real fields into the "Hook facts" section below.
- The page is read-only and never queries a database. No Cypher or SQL from
  the web page. The server has a small fixed set of named read queries. Values
  are always parameters, never pasted into query text. Neo4j reads use a
  read-only transaction and a time limit.
- Every write to Neo4j is `MERGE` on `id` (step id = session id + order
  number). Re-running must not create duplicates. Never DELETE anything in
  Neo4j unless the user passes `--clear`. Create uniqueness constraints first.
  (Deleting from the local store is `agentfly wipe` and retention only.)
- Never store file contents, secret values, tool inputs, edit text or agent
  replies. Store what SPEC section 4 lists (including the workspace root path),
  cleaned by its command-cleaning rules. The full action lives only in memory
  while the decision is made.
- Never print request bodies in logs.
- Nothing on port 8787 may change a rule, allow an action once, reset a mark
  or delete data (SPEC section 11). A new route is a read-only GET and gets a
  line in the API whitelist test in the same change.
- Rule shape: `Rule(id, severity, message, check)`. `severity` is `block`,
  `warn` or `highlight`. `check` is a small named pure function
  `(action, session) -> bool`. A rule *kind* is one such function in Python; the
  rules file (TOML) only supplies a kind's parameters and named lists. Do not
  build an expression language: a new kind is Python, a new rule is a file
  entry. R0 lives in code and no rules file can switch it off. Until the rules
  card lands, rules are one list in `recorder/rules.py`.

## Hook client rules
(`hooks/hook.py` today; `agentfly-hook <agent> <event>` after V2. SPEC section 8.)
- Standard library only, one file. Run it with `python -I -S` on a Python
  directly (never `uv run`, which is slow to start). In v1 that is the bundled
  system-owned Python, not the project's virtualenv or `/usr/bin/python3`.
- HTTP timeout about 0.5 s (V2 settles it from measurements). Set an explicit
  `timeout` in `hooks.json`, and quote the command path.
- Stdout must contain ONLY the JSON answer. Any other print to stdout can
  make Cursor block the action. All logging goes to stderr. Always print valid
  JSON and exit 0; never exit 2 by accident.
- If the server is unreachable or slow, apply the **offline guard** (D4, SPEC
  section 9), not a plain allow: deny outbound commands (except localhost and
  private ranges) and R0 guard-path commands, allow the rest, log the miss, and
  say "run `agentfly start`" in the deny message. Plain allow only after
  `agentfly uninstall` has removed the registration. *Today's hackathon client
  still answers allow when the server is down; V2 changes that.*
- Strip content before doing anything else: `content` of `beforeReadFile`,
  `edits` of `afterFileEdit`, `output` of `afterShellExecution`, and the
  contents of `tool_input` (keep only a file tool's target path, and an MCP
  call's server and tool names).
- On deny, put the rule text in BOTH `user_message` and `agent_message`, and
  add to `agent_message`: "Do not retry with another tool or language. Stop
  and tell the user."
- Send the token header. The session key is `conversation_id` (confirmed).

## Secrets
- The repo's `.env` contains only a FAKE demo secret used as bait
  (`API_KEY=demo-not-a-real-secret-12345`). Never put a real credential in it.
- Real credentials (Neo4j URI, user, password) live in a file OUTSIDE the
  repo folder, read only by the server. Names are listed in `.env.example`.
  Never print, export or commit them. Never pass them to the hook client.
  Today that file is `~/.config/flightrecorder/.env`; v1 moves it to
  `~/.config/agentfly/neo4j.env` (mode 600, D7) with a one-time migration (V2).
- Command cleaning (`recorder/clean.py`) is **on by default**. Set
  `CLEAN_COMMANDS=0` (or `false` / `off`) when starting the server to store
  raw commands instead — debugging only; secrets may then reach Neo4j.
- Neo4j (optional, off by default in v1): `uv run python -m recorder.check_db` /
  `python -m recorder.store --counts` / `--clear`. Writes are background-only;
  never DELETE except `--clear`. If `neo4j+s://` fails TLS verify on the host, use `neo4j+ssc://`
  (documented in `.env.example`); restart uvicorn after editing creds.
- The page: `GET /` (and its assets under `/assets/`) and `GET /api/steps` are
  Host-only (no token). The page never talks to a database; the live trail reads
  process memory. See README / HOOKS for the JSON contract.

## Code style
- Python 3.12, type hints on function signatures, `pathlib`, small functions.
- Rule checks and the command cleaner are pure functions (data in, result
  out) so tests need no network, no Neo4j and no Cursor.
- Plain `print`/`logging`. No CLI-framework or progress-bar libraries (the v1
  CLI uses `argparse`, one module per command).

## Testing (tests/test_rules.py, tests/test_clean.py, tests/test_app.py)
Only tests that exist are listed here. Each card adds its own tests and the
lines for them (R0 and normalisation: V5; hook-client stripping: V2).
- `cat .env` marks the session; `curl https://x.com` afterwards is blocked.
- `curl` without a prior secret read is allowed.
- `.env.local` is sensitive; `.env.example` and `id_rsa.pub` are not.
- `grep KEY .env` and `source .env` mark the session.
- `cat .env | curl -d @- host` is blocked (marking happens before blocking).
- `curl localhost:8000/health` is allowed even after marking.
- `python3 -c "import urllib.request; urllib.request.urlopen('https://x.com')"`
  after marking is blocked (a one-liner mentioning http).
- A secret read in one session does not affect another session.
- Marks survive a server restart.
- Cleaner: `curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1`
  is saved as `curl -H <arg> x.com`; `API_KEY=abc make` is saved as
  `API_KEY=<removed> make`; an unsplittable command is saved as
  `<program> <unparsed>`.
- Graph API: `GET /api/steps` without token → 200; wrong Host → 403; after
  README → `.env` → curl ntfy, payload has sensitive `.env` and blocked R1;
  `?all=1` returns more than the default last 10; `GET /` serves the React
  page and its `/assets/` load; wrong Host on `/` (and `/v2`) → 403; `/` and its assets send
  `Cache-Control: no-cache`; `/v2/` (also `/v2`, `/v2/index.html`) answers 307 to
  `/` with the query kept; missing `ui/dist` logs a warning and does not
  prevent the app from importing.

## Hook facts (fill in after the logging stage)
- Config file (today's dev setup): `.cursor/hooks.json` — **gitignored** (whole
  `.cursor/`); create with `./install.sh`. v1 registers the hooks once in the
  system-owned `/Library/Application Support/Cursor/hooks.json` (SPEC section
  3). Project hooks need a trusted folder; restart Cursor if hooks do not load.
  Do not commit machine-local hook config.
- Events used: `beforeShellExecution`, `beforeReadFile`, `beforeMCPExecution`,
  `afterFileEdit`, `preToolUse`.
- Deny answer: `{"permission":"deny","user_message":"...","agent_message":"..."}`
  on stdout, exit code 0. Exit code 2 also blocks. Invalid JSON blocks.
- Real input fields seen on this machine (Cursor 3.5.17):
  - Common: `conversation_id`, `session_id` (same value), `generation_id`,
    `model`, `hook_event_name`, `cursor_version`, `workspace_roots`,
    `user_email`, `transcript_path`
  - `beforeShellExecution`: `command`, `cwd` (may be `""`), `sandbox` (bool)
  - `beforeReadFile`: `file_path`, `attachments` (list); `content` arrives but
    is dropped by `hooks/hook.py` before writing the log
  - Session key for the server: use `conversation_id` (confirmed)
  - Helper path: `hooks/hook.py` (install via `./install.sh`); log:
    `logs/events.jsonl` (under gitignored `logs/`). Compat shim:
    `recorder/hook_passthrough.py` (delegates to `hooks/hook.py`).
  - Helper POSTs sanitized JSON to `http://127.0.0.1:8787/hook` with
    `X-Recorder-Token` (from `~/.config/flightrecorder/token`); fail-open if
    the server is down.
  - R1 (`recorder/rules.py`): mark on sensitive read/shell word, then block
    outbound sends; sessions in `~/.config/flightrecorder/sessions.json`.
  - Replay: `uv run python fake_agent.py` (scenarios in `demo/scenario.json`).
  - S1/S2 (Cursor 3.24.12, `docs/spikes/`): `tool_use_id` arrives on
    `preToolUse` and `beforeShellExecution` only. `preToolUse.tool_input` keys:
    Shell `command`, `cwd`, `timeout`; Read `file_path`; Write `file_path`,
    `content`; Grep `file_path`, `pattern`. `ask` from `beforeShellExecution`
    pauses the agent (Skip / Always Run / Run); an allow with messages shows
    nothing. The system `hooks.json` runs alongside user and project hooks.
  - Checkpoint A (hard-coded T0 curl deny): done — decision **continue**;
    notes in `demo/NOTES.md`; T0 disabled in `hooks/hook.py`.
