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

The hackathon spec is in git history only: `git show 3871787:docs/archive/SPEC-hackathon.md`.

A "card" is one of the maintainers' work items; cards, their briefs and reports and the
decisions (D-numbers, see SPEC.md's header) live in a private repo. An outside contributor
treats the issue or pull request as the card and puts the gap notes in the pull request.

## Commands
- Install deps: `uv sync`
- Install for every project (one `sudo`; bundled Python and hook client in
  `/Library/Application Support/AgentFly/`, tagged entries in
  `/Library/Application Support/Cursor/hooks.json`): `agentfly init -g`. Remove it:
  `agentfly uninstall` (our entries first, then the folder). Quit and reopen Cursor after
  either: it reads the system file only at start-up. The installed client is a copy, so a
  hook client change needs `init -g` again.
- Run the recorder as a service (no `sudo`): `agentfly start` writes and loads
  `~/Library/LaunchAgents/dev.agentfly.recorder.plist` (`KeepAlive`; `brew services` inside a
  Homebrew keg) and waits for `/health`; `agentfly stop` unloads it and deletes the file;
  `agentfly status` says who runs it and what `/health` answers. `agentfly uninstall` removes it
  too. A dev checkout runs `uv run agentfly serve` instead; both on port 8787 do not work.
- Check an install: `agentfly doctor` (one line per check, exit 1 on any fail, no password).
- Dev-only wiring (writes gitignored `.cursor/hooks.json`): `./install.sh`. With `init -g`
  also installed, every event arrives twice.
- Clear saved history (not marks, not Neo4j): `agentfly wipe`. R0 denies it to the agent.
- Rules: `agentfly rules check [FILE]` and `agentfly rules test [FILE]` (no FILE: the file the
  recorder would load, the active `/Library/Application Support/AgentFly/rules.toml` if it exists,
  else `agentfly/rules/default.toml`). The recorder reads the active file once, at start, and only
  believes it if it is a plain file owned by root that group and others cannot write (D3); the
  active file is read that way by `doctor` and by these commands too, other files are drafts.
  `rules test` exits 1 for a file with no tests. A file must keep R1 at least as strong as the
  program's minimum (D27) and stay under the work limit (`rulefile.MAX_WORK`, 200 units: the packaged
  default uses 31; a name pattern is 1, a slash pattern 4 plus 12 per `**` plus 1 per part past the
  fourth).
  `init -g` writes the file when missing, replaces it when it is byte for byte a default the
  package once carried (D28; the hashes are `rulefile.SHIPPED_DEFAULTS`, the new one goes in
  whenever `default.toml` changes), and keeps an edited one; a recorder restart applies a change.
- Check (run before you report a step done): `uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup`
  The tests run in parallel; the `env` keeps byte-code out (another worker's `.pyc` would
  break `test_nothing_is_written_next_to_the_client`). The flags stay on the command line,
  never in `addopts`: the live-Neo4j test starts its own `pytest`. CI runs this same line.
- Serial test run (one core, for a failure you cannot explain in parallel): `uv run pytest -q`
- Web check: `npm --prefix ui ci && npm --prefix ui run check`
- Stale-build check: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"`
- Auto-fix style: `uv run ruff check --fix . && uv run ruff format .`
- Run server: `uv run agentfly serve` (127.0.0.1 only; `--port N` or `AGENTFLY_PORT=N` for
  tests only: hooks always post to 8787, D25). A second `serve` on a busy port exits 1 and
  changes nothing.
- Build the wheel (carries `ui/dist`): `uv build`; try it with `uv tool install dist/*.whl`
- Replay a scripted session without Cursor: `uv run python examples/fake_agent.py`
- UI dev server (proxies `/api` to the recorder): `npm --prefix ui run dev`

## Approved dependencies (no need to ask)
Python: fastapi, uvicorn, httpx, neo4j (driver), pytest, pytest-xdist (with its
`execnet`), ruff, and hatchling (build backend, D6). Standard-library
`tomllib`, `sqlite3` and `argparse` need no approval. The **bundled Python
runtime** (D5) is also approved: a relocatable standalone build (the kind uv
downloads) that `agentfly init -g` installs for the hook client; the packaging
card picks the exact build. Ask before adding anything else.

JavaScript (npm **only inside `ui/`**; commit `ui/dist`, ignore
`ui/node_modules` via `ui/.gitignore`): vite, react, react-dom, typescript,
tailwindcss, `@tailwindcss/vite`, vitest, `@vitejs/plugin-react`,
`@testing-library/react`, jsdom, `@types/node`, `@types/react`,
`@types/react-dom`, `@xyflow/react` and `motion` (the last two are pinned in
`ui/package.json`). The page at `/` is the Vite build in `ui/dist`.

CI: GitHub Actions, `.github/workflows/ci.yml` only, on a hosted macOS runner (owner
2026-10-19). Ask before adding an action or another workflow. `.github/dependabot.yml` holds one
`github-actions` entry (weekly, one group, 7-day cooldown) and no uv or npm entry: those get
alerts and security updates from repository settings, and `@xyflow/react` and `motion` stay
pinned. CodeQL is GitHub's default setup, a repository setting with no workflow file. Dependabot
PRs are never merged on GitHub: the lead folds them into a card.

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
  `warn` or `highlight`; the strictest firing rule wins and a tie goes to file order.
  `check` is a small named pure function `(action, session) -> bool`. A rule *kind*
  (`match`, `after_then`) is such a function in Python; the rules file (TOML) only
  supplies a kind's parameters and named lists. Do not build an expression language:
  a new kind is Python, a new rule is a file entry. R0 lives in code and no rules file
  can switch it off or name it. R1 and its sensitive-name lists are the first entry of
  `agentfly/rules/default.toml`; only its engine-only outbound cases stay in Python
  (`command_class = "outbound"`). `agentfly/recorder/rulefile.py` reads and checks the
  file (it never raises and reads no environment); `rules.py` composes the rules. Every reader of
  a rules file goes through `rulefile.load_bytes`, which also holds the program's minimum for R1
  (D27: an `after_then` block whose `after` marks every name SPEC §5 counts as secret on read and
  shell, with exceptions only SPEC §5's two (`.env…` ending `.example`/`.sample`/`.template`,
  `id_rsa…` ending `.pub`), and whose `then` is exactly outbound shell; widening and rewording are
  fine) and the work budget.
  `Session.marked` is R1's trigger; every other `after_then` rule's trigger is its id
  in `Session.triggers`. No flag or variable moves the active file or who must own it: tests set
  `rulefile.ACTIVE_RULES` and `rulefile.ACTIVE_OWNER_UID`.

## Hook client rules
(`agentfly/hook_client.py`, installed as `agentfly-hook`; `hooks/hook.py` is a shim for it
until V3. Called as `agentfly-hook <agent> <event>`; with no arguments it acts as `cursor`.
SPEC section 8.)
- Standard library only, one file. Run it with `python -I -S` on a Python
  directly (never `uv run`, which is slow to start). In v1 that is the bundled
  system-owned Python, not the project's virtualenv or `/usr/bin/python3`.
- Posts only to `127.0.0.1:8787` (D25): no port file, no environment override. Tests
  set the client's port inside the test harness. HTTP wait 0.5 s (V2b measured it;
  p95 69 ms with the recorder up, accepted until V3 re-measures). Set an explicit
  `timeout` in `hooks.json`, and quote the command path.
- Stdout must contain ONLY the JSON answer. Any other print to stdout can
  make Cursor block the action. All logging goes to stderr. Always print valid
  JSON and exit 0; never exit 2 by accident.
- If the server is unreachable or slow, apply the **offline guard** (D4, SPEC
  section 9), not a plain allow: deny outbound commands (except localhost and
  private ranges) and R0 guard-path commands, allow the rest, log the miss, and
  say "run `agentfly start`" in the deny message. Plain allow only after
  `agentfly uninstall` has removed the registration. A 401 or 403 from the
  recorder (wrong token) and input the client cannot parse get the same guard,
  never an allow. Every inline `python -c` / `node -e` is denied offline.
- Strip content before doing anything else: `content` of `beforeReadFile`,
  `edits` of `afterFileEdit`, `output` of `afterShellExecution`, and the
  contents of `tool_input` (keep only a file tool's target path, and an MCP
  call's server and tool names), and any nested `content` / `output` (for
  example `attachments[].content`). The hook log keeps no command text.
  Top-level fields such as `parent_tool_call_id` pass through (D21).
  Session events (`sessionStart`, `sessionEnd`, `subagentStart`) keep only ids and
  names; `subagentStart.task` (the subagent's prompt) never leaves the client.
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
  That file is `~/.config/agentfly/neo4j.env` (mode 600, D7). The recorder's
  first start moves the hackathon `~/.config/flightrecorder/.env` there once.
- Command cleaning (`agentfly/recorder/clean.py`) is **on by default**. Set
  `CLEAN_COMMANDS=0` (or `false` / `off`) when starting the server to store
  raw commands instead — debugging only; secrets may then reach Neo4j.
- Local history: SQLite `~/.local/share/agentfly/history.db`, 28-day retention (D14).
- Neo4j (optional, off by default): runs only with `neo4j = true` in
  `~/.config/agentfly/config.toml`; `neo4j.env` alone does not turn it on. `uv run python -m agentfly.recorder.check_db` /
  `python -m agentfly.recorder.store --counts` / `--clear`. Writes are background-only;
  never DELETE except `--clear`. If `neo4j+s://` fails TLS verify on the host, use `neo4j+ssc://`
  (documented in `.env.example`); restart the server after editing creds.
- Tests never use that login. The live Neo4j tests run only when
  `AGENTFLY_TEST_NEO4J_ENV` names a separate credentials file for a test
  database, and skip otherwise; never point it at the owner's AuraDB.
- The page: `GET /` (and its assets under `/assets/`) and `GET /api/steps` are
  Host-only (no token). The page never talks to a database; the live trail reads
  process memory. See README / HOOKS for the JSON contract.

## Code style
- Python 3.12, type hints on function signatures, `pathlib`, small functions.
- Rule checks and the command cleaner are pure functions (data in, result
  out) so tests need no network, no Neo4j and no Cursor.
- Plain `print`/`logging`. No CLI-framework or progress-bar libraries (the v1
  CLI uses `argparse`, one module per command).

## Testing
What each test file checks is listed in `tests/README.md`; read the lines for a file before you
change it. Each card adds the lines for its own tests there, not in this file.

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
    is dropped by the hook client before writing the log
  - Session key for the server: use `conversation_id` (confirmed)
  - Helper path: `agentfly/hook_client.py` (`agentfly-hook`); `./install.sh` wires
    the shim `hooks/hook.py`. Log: `~/.local/share/agentfly/logs/events.jsonl`
    (dir 700, file 600). Compat shim: `recorder/hook_passthrough.py` (delegates
    to `hooks/hook.py`).
  - Helper POSTs sanitized JSON to `http://127.0.0.1:8787/hook` with
    `X-Recorder-Token` (from `~/.config/agentfly/token`); offline guard if
    the server is down, slow or answers 401/403.
  - R1 (first entry of `agentfly/rules/default.toml`, engine in `agentfly/recorder/rules.py`):
    mark on a sensitive read/shell word, then block outbound sends; sessions in
    `~/.local/share/agentfly/sessions.json`.
  - Replay: `uv run python examples/fake_agent.py` (scenarios in `examples/scenario.json`).
  - S1/S2 (Cursor 3.24.12, spikes S1 and S2): `tool_use_id` arrived on
    `preToolUse` and `beforeShellExecution` only (`beforeReadFile` has it from 3.25.9, see
    V2c). `preToolUse.tool_input` keys:
    Shell `command`, `cwd`, `timeout`; Read `file_path`; Write `file_path`,
    `content`; Grep `file_path`, `pattern`. `ask` from `beforeShellExecution`
    pauses the agent (Skip / Always Run / Run); an allow with messages shows
    nothing. The system `hooks.json` runs alongside user and project hooks.
  - S5 (Cursor 3.24.12): a subagent has its own `conversation_id` and carries
    `parent_tool_call_id` on every event (D21 A links it to the parent's mark).
    One unknown event name disables a whole `hooks.json` (D23);
    `~/.claude/settings.json` is a third hook source (D24).
  - V3a (Cursor 3.25.9, 2026-10-18): the system file loads at start-up only (Hooks log:
    `Loaded N enterprise hook(s)` / `No enterprise hooks configuration found`); Settings →
    Hooks does not list system hooks. A missing interpreter exits 127 and Cursor lets the
    action through; a missing client file exits 2 and Cursor denies everything. A
    `~/.claude/settings.json` allow did not cancel our shell deny (one trial).
  - V2c (Cursor 3.25.9, spike V2c): `beforeShellExecution` carries the
    same `tool_use_id` as its `preToolUse` Shell (34 of 34) and `beforeReadFile` as its
    `preToolUse` Read (28 of 28; all read paths absolute). One id covers an edit's Read and
    Write; `afterFileEdit` has no id and fired for a create only; parallel reads' halves can
    return in reverse order. A Read of a missing file fires no `beforeReadFile`. The server
    merges by id, with a path fallback (SPEC section 8 "Duplicates").
  - Checkpoint A (hard-coded T0 curl deny): done — decision **continue**;
    notes in `git show 38e8879:demo/NOTES.md`; T0 disabled in the hook client.
