# AGENTS.md — AgentFly

## What this project is
Cursor hooks send every agent action to a local server. The server decides
allow, warn or block using rules, and saves a cleaned copy to a local store
(Neo4j is an optional extra copy). A web page shows the session live.

`SPEC.md` is the **v1 target**: read the sections your card cites, not the whole file.
The code moves toward it card by card. So:
- Inside your card, follow SPEC.md and the card.
- Outside your card, leave the code as it is and note the gap in your report.
- If SPEC.md and your card disagree, stop and ask. Do not silently pick one.

The hackathon spec (history only): `git show 3871787:docs/archive/SPEC-hackathon.md`.

A "card" is one of the maintainers' work items; cards, briefs, reports and the decisions
(D-numbers, see SPEC.md's header) live in a private repo. An outside contributor treats the
issue or pull request as the card and puts the gap notes in the pull request.

## Where things are
- `agentfly/cli/`: the `agentfly` commands, one module each. `agentfly/install/`: `init -g`,
  `uninstall`, `doctor`, the service. `agentfly/rules/`: the packaged `default.toml`.
- `agentfly/recorder/`: the server, rules engine, sessions, cleaner, local store, Neo4j.
- `agentfly/hook_client.py`: the hook client. `hooks/hook.py`: the dev shim `./install.sh` wires.
  The top-level `recorder/` forwards a stale `hooks.json` to that shim. Keep both files: a
  missing one exits 2, which locks the agent.
- `ui/`: the page (`ui/dist` is the committed build). `examples/`: the replay tool.
  `tests/`: see `tests/README.md`.

## Commands
- Install deps: `uv sync`
- Install for every project (one `sudo`, SPEC §7): `agentfly init -g`. Remove it: `agentfly uninstall`.
  Quit and reopen Cursor after either: it reads the system file only at start-up. The installed
  client is a copy, so a hook client change needs `init -g` again.
- Run the recorder as a service (no `sudo`, SPEC §7): `agentfly start`, `agentfly stop`,
  `agentfly status`. A dev checkout runs `uv run agentfly serve` instead; both on port 8787 do not work.
- Check an install: `agentfly doctor` (one line per check, exit 1 on any fail, no password).
- Dev-only wiring (writes gitignored `.cursor/hooks.json`, never commit it): `./install.sh`. With
  `init -g` also installed, every event arrives twice.
- Clear saved history (not marks, not Neo4j): `agentfly wipe`. R0 denies it to the agent.
- Rules: `agentfly rules check [FILE]` and `agentfly rules test [FILE]` (no FILE: the file the
  recorder would load). SPEC §5 says which file is in force and what a file may cost. The active
  file is read once, at start, and only if root owns it and others cannot write it (D3). Add the
  hash of a changed `default.toml` to `rulefile.SHIPPED_DEFAULTS` (D28).
- Check (run before you report a step done): `uv run ruff check . && uv run ruff format --check . && env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup`
  The tests run in parallel; `env` keeps byte-code out (a stray `.pyc` breaks
  `test_nothing_is_written_next_to_the_client`). Keep the flags on the command line, never in
  `addopts`: the live-Neo4j test starts its own `pytest`. CI runs this same line.
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
runtime** (D5) is also approved: a relocatable standalone build that
`agentfly init -g` installs for the hook client. Ask before adding anything else.

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
pinned. CodeQL is GitHub's default setup (no workflow file). Dependabot PRs are never merged
on GitHub: the lead folds them into a card.

## Working rules
- One card at a time. Do only the card you were asked for, then STOP and say
  what works and what does not. Do not start the next card. The card says what
  you may touch.
- Run each check bare, never through a pipe (`cmd | tail` hides its failure).
- The block decision uses in-memory state only. It never waits for a database
  or the network. Writes to the local store (and to Neo4j, when enabled) happen
  in the background and must never slow or break a hook response.
- Do not guess how Cursor hooks behave. Log the real input first (with file
  contents thrown away), then code against what actually arrives. Put what you
  learn in HOOKS.md "Observed on Cursor".
- The page is read-only and never queries a database: no Cypher or SQL from it. The
  server has a small fixed set of named read queries; values are always parameters,
  never pasted into query text. Neo4j reads use a read-only transaction and a time limit.
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
  (`command_class = "outbound"`).
- `agentfly/recorder/rulefile.py` reads and checks a rules file (it never raises and reads only
  the home folder, through `expanduser`); `rules.py` composes the rules. Every reader of a rules
  file goes through `rulefile.load_bytes`, which also holds the program's minimum for R1 (D27,
  SPEC §5: a file may widen R1 or reword it, never weaken it) and the work budget.
  `Session.marked` is R1's trigger; every other `after_then` rule's trigger is its id
  in `Session.triggers`. No flag or variable moves the active file or who must own it: tests set
  `rulefile.ACTIVE_RULES` and `rulefile.ACTIVE_OWNER_UID`.

## Hook client rules
(`agentfly/hook_client.py`, installed as `agentfly-hook`; the dev shim is under "Where things
are". Called as `agentfly-hook <agent> <event>`; with no arguments it acts as `cursor`. SPEC
section 8.)
- Standard library only, one file. Run it with `python -I -S` on a Python
  directly (never `uv run`, which is slow to start). In v1 that is the bundled
  system-owned Python, not the project's virtualenv or `/usr/bin/python3`.
- Posts only to `127.0.0.1:8787` (D25): no port file, no environment override. Tests
  set the client's port inside the test harness. HTTP wait 0.5 s (SPEC section 8). Set an explicit
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
- Strip content before doing anything else: file contents, edit text, command output,
  `tool_input` except a file tool's path and an MCP call's names, any nested `content` /
  `output`. The log keeps no command text. Top-level fields such as `parent_tool_call_id` pass
  through (D21). Session events keep only ids and names; `subagentStart.task` never leaves the
  client. Fields: SPEC section 8 "Stripping"; every depth: HOOKS.md "Hook client behaviour" step 2.
- On deny, put the rule text in BOTH `user_message` and `agent_message`, and
  add to `agent_message`: "Do not retry with another tool or language. Stop
  and tell the user."
- Send the token header.

## Secrets
- The repo's `.env` contains only a FAKE demo secret used as bait
  (`API_KEY=demo-not-a-real-secret-12345`). Never put a real credential in it.
- Real credentials (Neo4j URI, user, password) live in a file OUTSIDE the
  repo folder, read only by the server. Names are listed in `.env.example`.
  Never print, export or commit them. Never pass them to the hook client.
  That file is `~/.config/agentfly/neo4j.env` (mode 600, D7).
- Command cleaning (`agentfly/recorder/clean.py`) is **on by default**. Set
  `CLEAN_COMMANDS=0` (or `false` / `off`) when starting the server to store
  raw commands instead (debugging only; secrets may then reach Neo4j).
- Local history: SQLite `~/.local/share/agentfly/history.db`, 28-day retention (D14).
- Neo4j (optional, off by default): runs only with `neo4j = true` in
  `~/.config/agentfly/config.toml`; `neo4j.env` alone does not turn it on. Its commands and the
  `neo4j+ssc://` TLS note are in HOOKS.md "Neo4j background store". Restart the server after
  editing creds.
- Tests never use that login. The live Neo4j tests run only when
  `AGENTFLY_TEST_NEO4J_ENV` names a separate credentials file for a test
  database, and skip otherwise; never point it at the owner's AuraDB.
- The page: `GET /` (and `/assets/`) and `GET /api/steps` are Host-only (no token). The live
  trail reads process memory. JSON contract: README / HOOKS.

## Code style
- Python 3.12, type hints on function signatures, `pathlib`, small functions.
- Rule checks and the command cleaner are pure functions (data in, result
  out) so tests need no network, no Neo4j and no Cursor.
- Plain `print`/`logging`. No CLI-framework or progress-bar libraries (the v1 CLI uses `argparse`).

## Testing
What each test file checks is listed in `tests/README.md`; read the lines for a file before you
change it. Each card adds the lines for its own tests there, not in this file.

## Hook facts
- Gates (can deny): `beforeShellExecution`, `beforeReadFile`, `beforeMCPExecution`, `preToolUse`.
  Recorded only: `afterFileEdit`, `sessionStart`, `sessionEnd`, `subagentStart`. The session
  key is `conversation_id`.
- Deny answer: `{"permission":"deny","user_message":"...","agent_message":"..."}` on stdout, exit
  code 0 (exit 2 also blocks; invalid JSON blocks).
- Log the real input before coding against it. Seen so far, by version: HOOKS.md "Observed on Cursor".
