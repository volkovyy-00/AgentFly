# AgentFly v1 board (revision 3)

Status: **spikes S1–S5 may start now. v1 cards (V1–V9) wait for your approval
of `docs/DECISIONS.md`.** After approval, any card whose plan depends on a
decision you changed is rewritten before it starts.

Revision 3 (2026-10-15) applies your Rev 2 review: spikes unblocked; S1's
send-out target is non-receiving; the UI draft form is dropped for v1; the API
test allows HEAD only on static and plain Starlette routes and asserts 405
elsewhere; D4, D10, D14 and D20 are approved (see
DECISIONS.md). D1 is approved as [A] (sudo by default; wording "prevented for
config and rules; detected for tampering with installed code"); V3 and V7 are
written for it.

Revision 2 (2026-10-14) applies your review:
- `tool_input` stripping and its tests (V2);
- command normalisation for R1 (V5);
- forum-sourced bugs marked "to reproduce" (SYNTHESIS §1.1);
- `ask` and allow-message checks added to S1, and the S2 tamper list extended;
- the split API and its test (D19, V2);
- parallel lanes and one module per CLI command;
- V3 and V7 split, which renumbers the later cards;
- S5 recast as a smoke test;
- per-project `init` deferred (D20).

Because of the requested splits, the board now has **14 cards**, two above the
first request's cap of 12.

## Rules for every card
- Report what works and what doesn't, then stop (AGENTS.md "One step at a
  time"). Cards marked ∥ may run at the same time in separate worktrees.
- **Worktrees.** Each card gets its own git worktree and branch,
  `ag-<card>-<slug>`. Parallel cards have non-overlapping "May touch" lists,
  apart from the declared merge points below.
- **Declared merge points.** These are expected one-line conflicts; whichever
  PR merges second resolves them:
  - the router list in `agentfly/recorder/app.py`;
  - the route whitelist in `tests/test_api_surface.py`.

  Both are shared on purpose: every new route has to be added consciously
  (D19).
- **CLI.** Each subcommand is its own module in `agentfly/cli/commands/`. The
  dispatcher from V2 discovers them, so adding a command never edits a shared
  file.
- Code cards are done only when the AGENTS.md check command passes, plus the web
  check and the stale-build check when `ui/` changed. Evidence goes in the PR
  description.
- Spike cards write no product code. Results go in `docs/spikes/<id>.md`. Any
  file a spike changes outside the repo is backed up first and restored after.
- "May touch" is a whitelist. Anything else needs the lead's OK first.
- Spikes S1, S2, S4 and S5 need you at the keyboard: the Cursor app, `sudo`,
  and your judgement.

## Lanes

```
Spikes        Lead (your machine): S1 ──► S2 ──► S5
              Backend:             S3              (∥ S1, S2)
              UI:                  S4              (∥ S1, S2)

              ─────────── you approve DECISIONS.md ───────────

v1            Lead:     V1
              Backend:  V2 ──┬──► V3  CLI install commands ──┐
                             ├──► V4  formula + release      │ (V4's last check needs V3)
                             ├──► V5  rules + R0 ──────┬─────┼──► V7  rule change flow
                             └──► V6  local store ─────┤     │
              UI:       V8  trail + Why + health  (starts after V1, merges after V2)
                             └──────────────────────► V9  History + Rules tabs (after V5, V6, V8)
```

V3, V4, V5 and V6 can all run in parallel once V2 has merged. V7 and V9 can run
in parallel.

---

## Spikes (steps and pass rules are in `docs/SYNTHESIS.md` §3)

### S1 · G1 · Global hooks fire in a fresh folder; `ask` and allow messages
- **Owner:** lead (you at the keyboard)
- **Lane:** lead, first
- **Time box:** 45 min. That is 30 for the global-hook test and 15 for the two
  answer checks you added. The throwaway stub is written before the clock
  starts.
- **May touch:** `~/.cursor/hooks.json` (created, then removed); the repo's
  `.cursor/hooks.json` (moved aside, then restored); `/tmp/af-fresh/`;
  `/tmp/af-spike/stub.py` (throwaway, never committed); new
  `docs/spikes/S1-global-hooks.md`.
- **Done when** `docs/spikes/S1-global-hooks.md` records:
  - the Cursor app and `cursor-agent` versions, and the exact `hooks.json`
    used;
  - event counts by type for the fresh folder, plus a screenshot of the R1 deny
    in the app and the CLI output;
  - whether `tool_use_id` arrived;
  - whether `ask` pauses the agent and asks you, in the app and in the CLI;
  - whether `user_message` is shown, and `agent_message` used, when the answer
    is allow;
  - the key names (never values) inside `preToolUse.tool_input` for Write,
    Read, Grep and one MCP tool;
  - pass or fail against SYNTHESIS §3, and what it changes in D2, D9 and D11.

### S2 · Hard constraint · Root-owned registration and tamper attempts
- **Owner:** lead (you at the keyboard, `sudo`)
- **Lane:** lead, after S1
- **Time box:** 60 min, for nine attempts.
- **May touch:** `/Library/Application Support/Cursor/hooks.json` and
  `/Library/Application Support/AgentFly/` (created, then removed);
  `~/.cursor/hooks.json`; `/tmp/af-fresh/` (including `.cursor/`); new
  `docs/spikes/S2-tamper.md`.
- **Done when** `docs/spikes/S2-tamper.md` has:
  - whether hooks fire from the system file, with event counts;
  - a table of tamper attempts (a)–(i), each with its command, result, error
    text and whether AgentFly still denied a follow-up `curl`;
  - whether `/usr/bin/python3` exists;
  - who owns `$(brew --prefix)/Cellar`;
  - pass or fail, with the resulting choices for D1, D2, D3, D5 and D19.

### S3 · G2 · Do your rules fit the fixed kinds; drafting accuracy
- **Owner:** worker-backend (input: your 10 sentences)
- **Lane:** backend, ∥ S1 and S2
- **Time box:** 30 min, after your sentences arrive. A cloud model needs your
  OK first (D13).
- **May touch:** new `docs/spikes/S3-rule-fit.md` and new
  `docs/spikes/S3-rules.toml` (paper format only, never loaded by code).
- **Done when** `docs/spikes/S3-rule-fit.md` has:
  - the 10 sentences beside their hand-written TOML;
  - a list of misfits, each with what's missing;
  - the model's drafts beside the hand-written versions, as an exact-match
    count out of 10 and an invented-field count;
  - pass or fail, with the resulting choices for D10 and D13.

### S4 · G3 · Static trail mock vs today's page
- **Owner:** worker-ui (you judge)
- **Lane:** UI, ∥ S1 and S2
- **Time box:** 30 min.
- **May touch:** new `docs/spikes/S4-trail-mock.html` (one static file, no
  build, never served by the app) and new `docs/spikes/S4-trail.md`.
- **Done when** `docs/spikes/S4-trail.md` has:
  - screenshots of the mock and of today's page on the same 200+ step mock
    session;
  - your choice, plus what you said is missing;
  - the resulting choice for D15.

### S5 · G4 · Smoke test: does a brief reach the agent at all (n = 2)
- **Owner:** lead (you at the keyboard)
- **Lane:** lead, after S2 (it reuses `/tmp/af-fresh`)
- **Time box:** 30 min.
- **May touch:** `/tmp/af-fresh/` (Makefile, `.cursor/rules/`); new
  `docs/spikes/S5-brief.md`.
- **Done when** `docs/spikes/S5-brief.md` has:
  - the brief text;
  - for each of the four chats, the commands before the first passing run,
    taken from the hook log;
  - whether the agent mentioned the brief;
  - the `additional_context` result, if tried.

  The report states that n = 2 per arm measures nothing about value. A pass only
  unlocks the pre-registered A/B (D16).

---

## v1 cards

### V1 · Rewrite SPEC.md and AGENTS.md from the approved decisions
- **Owner:** lead
- **Lane:** lead
- **Depends on:** all decisions approved; S1–S5 done
- **May touch:** `SPEC.md`, `AGENTS.md`, `HOOKS.md`, `README.md`,
  `docs/product-goals.md` (G1 flow wording only, per D6 and D20),
  `docs/DECISIONS.md` (status lines), new `docs/archive/SPEC-hackathon.md`.
- **Done when:**
  - The PR contains a table mapping each approved decision to its SPEC section.
  - AGENTS.md's Testing list names only tests that exist. The R0 line moves to
    V5. "The helper drops `content`" moves to V2, which writes that test.
  - The approved dependencies, paths, commands, rule shape, R1 outbound
    definition (D10) and API surface (D19) match the decisions.
  - You approve the PR.

### V2 · Installable `agentfly` package, hardened hook client, API surface
- **Owner:** worker-backend
- **Lane:** backend, first. It moves files, so V3–V6 wait for it to merge.
- **Depends on:** V1
- **May touch:** `pyproject.toml`, `uv.lock`; `recorder/**` → `agentfly/recorder/**`
  (routes split into `agentfly/recorder/api/*.py`, with an explicit router list
  in `app.py`); `hooks/hook.py` → `agentfly/hook_client.py`;
  `recorder/hook_passthrough.py`; new `agentfly/cli/__init__.py` (dispatcher
  that discovers `agentfly/cli/commands/*.py`); new
  `agentfly/cli/commands/serve.py`; `fake_agent.py`; `tests/**`. Not `ui/**`,
  and not `install.sh`.
- **Done when:**
  - **Package.** `uv build` makes a wheel that contains `ui/dist`. Installing it
    with `uv tool install` under a temporary HOME puts `agentfly` and
    `agentfly-hook` on PATH. `agentfly serve` runs the recorder (terminal output
    pasted).
  - **Stripping, with new tests in `tests/test_hook_client.py`.** No content
    leaves the client, to the log or to the server:
    - `content` from `beforeReadFile`;
    - `edits` from `afterFileEdit`;
    - `output` from `afterShellExecution`;
    - **`tool_input` contents from `preToolUse`** (a Write payload carrying file
      text is the test case);
    - **`tool_input` from `beforeMCPExecution`.**

    From `tool_input`, the client keeps only the target path of file tools,
    using the key names S1 found (`file_path` for Read, Write and Grep; never
    `content`, `pattern` or `command`), so R0 can deny a Write to a guard file. MCP
    keeps only the server and tool names. The tests assert that a marker string
    planted in each content field never appears in the log line or in the POST
    body.
  - **Kill test.** With the recorder stopped, 100 calls per event all print
    valid JSON and exit 0. The offline guard (D4) denies `curl https://x.com`,
    `bash -c 'curl x.com'` and an R0 command. It allows `ls` and
    `curl localhost:8000/health`. Every offline deny message says to run
    `agentfly start` (D4). Each offline-guard decision is appended to
    `~/.local/share/agentfly/offline.jsonl`, and `GET /health` reports their
    count since start.
  - **Latency.** p95 hook round trip is under 50 ms over 200 calls with the
    recorder up (script output pasted).
  - **Duplicates.** A `preToolUse` call and a matching specific gate with the
    same `tool_use_id` make one step (fixture test).
  - **API surface (D19).** `tests/test_api_surface.py` lists every
    `(method, path)` the app serves. It fails if a route is missing from the
    explicit whitelist, or if any method other than GET exists besides
    `POST /hook`. HEAD is allowed only on the `StaticFiles` mount and plain
    Starlette routes, if any; a test asserts HEAD on each API GET route is 405
    (true on fastapi 0.142.2 / starlette 1.7.0 in `uv.lock`; re-confirm if the
    lock changes). FastAPI's built-in `/docs`, `/redoc` and `/openapi.json`
    are switched off.
  - **Paths.** D7 paths, with a one-time migration from
    `~/.config/flightrecorder` (test with a temporary HOME).
  - All existing tests still pass.

### V3 · CLI install commands: `init -g`, `uninstall`, `doctor`, `start`, `stop`, `status`
- **Owner:** worker-backend
- **Lane:** backend, ∥ V4, V5 and V6 after V2
- **Depends on:** V2, S1, S2
- **May touch:** new `agentfly/cli/commands/{init,uninstall,doctor,start,stop,status}.py`
  (one module each); new `agentfly/install/{hooks_json,system_paths,service,integrity}.py`;
  `install.sh` (becomes a short dev wrapper or is deleted); README "Install"
  section; new `tests/test_install_*.py`.
- **Out of scope:** per-project `agentfly init` is deferred (D20).
- **First step, on your Mac:** add one made-up event name to `hooks.json` and
  check whether the other hooks still fire. This reproduces, or rules out, the
  "unknown event disables the file" report, and decides whether `init` must
  gate events by Cursor version.
- **Done when:**
  - Unit tests: merging into a `hooks.json` that holds another tool's entries
    leaves theirs byte-identical, tags ours, and writes a backup. Running `init`
    twice changes nothing. `uninstall` removes only our entries.
  - On your Mac (terminal log and screenshots in the PR):
    1. Install from the local wheel, run `agentfly init -g` (one `sudo`, per D2
       and D3), then `agentfly start`.
    2. Open a never-opened folder in Cursor and trigger the R1 deny **10
       times**: 10 of 10 must be denied. This reproduces, or rules out, the
       deny race on your machine.
    3. `agentfly doctor` is all green, including the integrity hash (D1).
    4. Kill the recorder: launchd `KeepAlive` restarts it (D4/D8; check both
       the brew-services and own-LaunchAgent plists). With KeepAlive off, or
       during the restart gap, `doctor` turns red, the offline guard denies
       `curl`, and the deny message says `agentfly start`.
    5. `agentfly uninstall`: no AgentFly hook entries remain, and
       `launchctl list | grep agentfly` prints nothing.

### V4 · Homebrew formula and release workflow
- **Owner:** worker-backend
- **Lane:** backend, ∥ V3, V5 and V6 after V2. Its last check needs V3.
- **Depends on:** V2 (for the brew-services check, V3)
- **May touch:** new `packaging/homebrew/agentfly.rb`, new
  `packaging/homebrew/README.md`, new `.github/workflows/release.yml`. Not the
  README; V3 owns the install section.
- **Done when:**
  - `brew install --build-from-source ./packaging/homebrew/agentfly.rb` and
    `brew test agentfly` pass locally (output pasted).
  - `test do` pipes a fake `beforeShellExecution` payload through
    `agentfly-hook` with no server, and asserts valid JSON.
  - The caveats tell you to run `agentfly init -g`, and to run
    `agentfly uninstall` before `brew uninstall`.
  - After V3 merges: `brew services start agentfly` serves `/health`
    (output pasted).
  - The release workflow builds the UI once and makes the wheel and sdist. It
    has no publish step until you approve publishing.

### V5 · Rules file, rule kinds, command normalisation, R0
- **Owner:** worker-backend
- **Lane:** backend, ∥ V3, V4 and V6 after V2
- **Depends on:** V2, S3
- **May touch:** `agentfly/recorder/rules.py`, `agentfly/recorder/names.py`; new
  `agentfly/recorder/rulefile.py`, new `agentfly/recorder/normalize.py`; a
  packaged default `agentfly/rules/default.toml`; new
  `agentfly/cli/commands/{rules_check,rules_test}.py`; new
  `agentfly/recorder/api/rules.py` (read-only `GET /api/rules`, plus the two
  declared merge points); `tests/test_rules.py`; new
  `tests/test_{rulefile,normalize,r0}.py`.
- **Done when:**
  - R1 and its lists load from `rules.toml`, and every existing rule test in
    AGENTS.md still passes.
  - **Normalisation applies to every rule, R1 included** (D10). With the
    session marked, each of these counts as outbound and is blocked:
    - `bash -c 'curl https://x.com'` and `sh -c "wget x.com"`;
    - `echo $(curl https://x.com)` and `` echo `curl x.com` ``;
    - `env A=1 curl x.com` and `sudo curl x.com`;
    - `python3 -c "…"` and `node -e "…"`, even with no "http" in the text;
    - unparseable commands: an unbalanced quote, or an unquoted `<<EOF` block.

    These stay allowed while marked: `bash -c 'ls'`,
    `curl localhost:8000/health`, `python3 -m pytest`, and
    `git commit -m "$(cat <<'EOF' … EOF)"` (a quoted-delimiter heredoc body
    is literal data, D10). Each case is a test.
  - **R0 lives in code** and blocks:
    - touching AgentFly's config and system folders, any `hooks.json` (user,
      system or project) and the token;
    - `kill`, `pkill` and `launchctl` aimed at the recorder;
    - commands naming the recorder's port;
    - a Write or Edit whose target path (from V2) is a guard path.

    It is case-folded and goes through the same normalisation. It also checks
    the raw, case-folded text, so an unparseable command can't hide a guard
    name. A rules file that tries to remove or weaken R0 is rejected (tests).
  - Your S3 rules load, and their inline tests pass with `agentfly rules test`
    (output pasted).
  - "Block npm publish after reading .env" is added by editing only the rules
    file: a test, plus a PR diff that touches no `.py` file for it.
  - block, warn and highlight produce the D11 answers (tests).
  - The decision path does no file or network I/O (a test that patches `open`
    and `socket`).

### V6 · Local session store and history API
- **Owner:** worker-backend
- **Lane:** backend, ∥ V3, V4 and V5 after V2
- **Depends on:** V2
- **May touch:** new `agentfly/recorder/localstore.py`,
  `agentfly/recorder/store.py` (Neo4j optional, off by default),
  `agentfly/recorder/memory.py`; new `agentfly/recorder/api/sessions.py`
  (`GET /api/sessions`, `GET /api/sessions/{id}/steps`, plus the two declared
  merge points); new `agentfly/cli/commands/wipe.py`; new
  `tests/test_{localstore,sessions_api}.py`.
- **Done when:**
  - Steps are written to SQLite in the background, and hook latency is
    unchanged (V2's benchmark re-run, both numbers pasted).
  - Sessions and steps survive a restart. The list shows the workspace (per
    D14), start and end, step, block and warn counts, and "marked by R1".
  - A schema test proves only SPEC §4 fields plus the approved new fields are
    stored, never content.
  - Retention follows D14, and `agentfly wipe` exists (tests).
  - The app runs with Neo4j unset (test), and the Neo4j copy still works when it
    is configured (existing tests).

### V7 · Rule change flow: draft, check, diff, backtest, `sudo` approve
- **Owner:** worker-backend
- **Lane:** backend, ∥ V9
- **Depends on:** V5, V6
- **May touch:** new
  `agentfly/cli/commands/{rules_draft,rules_diff,rules_backtest,rules_apply}.py`;
  `agentfly/recorder/rulefile.py`; new `agentfly/recorder/backtest.py`; new
  `agentfly/recorder/rules_reload.py`; new
  `tests/test_{rules_diff,backtest,rules_apply}.py`. **No new routes (D19).**
- **Done when:**
  - The diff marks loosening changes in red: a removed rule, a lower severity, a
    shorter list, a new exception (tests).
  - The backtest over fixture sessions prints "would change N decisions in M
    sessions", with step ids (test).
  - `apply` refuses without root. With root it installs atomically, and the
    recorder picks up the new version within 2 s without a restart (test, plus a
    manual check on your Mac).
  - As your normal user, writing the active rules file fails (manual evidence
    pasted).
  - `tests/test_api_surface.py` is unchanged by this card.
  - Plain-language drafting is not included unless D13 is approved.

### V8 · UI: trail home, Why card, health strip
- **Owner:** worker-ui
- **Lane:** UI. Starts after V1 and merges after V2 (for the `/health` count).
- **Depends on:** S4, V1; V2 for the merge
- **May touch:** `ui/src/**` except `ui/src/history/**` and `ui/src/rules/**`;
  `ui/dist` (rebuilt); ui tests. No Python. No new npm dependencies without
  your approval.
- **Done when:**
  - The home trail works on a 500-step mock session: routine runs are grouped,
    blocks, warnings and secret reads are never grouped, and Follow still works
    (tests and a screenshot).
  - Every block and warning opens a Why card with the rule id and text, the
    trigger step → blocked step, and the messages sent to you and to the agent.
    There is **no "allow once" button** (D19); the card shows the
    `agentfly rules …` command instead (test and screenshot).
  - The health strip shows recorder online/offline, the last hook seen, and the
    offline-guard count.
  - "Contents not recorded" appears wherever content would have been.
  - The web check and the stale-build check pass. A 60-second GIF of the R1 demo
    on the new page is attached.

### V9 · UI: History and Rules tabs
- **Owner:** worker-ui
- **Lane:** UI, after V8; ∥ V7
- **Depends on:** V5 (`GET /api/rules`), V6 (sessions API), V8
- **May touch:** new `ui/src/history/**` and `ui/src/rules/**`; the tab entry in
  the app shell; `ui/dist` (rebuilt); ui tests.
- **Done when:**
  - The History tab lists sessions from V6, and opening one shows its trail,
    read-only.
  - The Rules tab shows the active rules with severity, hit counts and last
    fired, read-only, plus the `agentfly rules` commands that change them.
    Nothing in the UI writes.
  - The web check and the stale-build check pass, and you say it is demo-ready.

---

## Not on the board (on purpose)
- **Publishing to PyPI and the Homebrew tap:** the lead does it, after your OK
  on each release. It is outward-facing.
- **G4 pre-registered A/B (4-memory-claude.md):** added only if S5 passes and
  V6 exists. It also needs `afterShellExecution` exit codes (D9).
- **Plain-language rule drafting:** added after S3's numbers and an approved
  D13.
- **Per-project `agentfly init`:** deferred (D20).
