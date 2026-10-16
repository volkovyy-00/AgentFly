# AgentFly v1 board (revision 3)

Status: **spikes S1–S4 are done; S5 may start. All decisions but D16
(after S5) are approved (2026-10-16); v1 cards
(V1–V9) wait for V1a.** V1 is split (owner, 2026-10-16): V1a rewrites SPEC.md and
AGENTS.md for the approved decisions now; V1b fills in what S3 and S5 change. After approval, any card whose plan depends on a
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

v1            Docs:     V1a (worker, ∥ S3) ──► Lead: V1b (after S3, S5)
              Backend:  V2 ──┬──► V3  CLI install commands ──┐
                             ├──► V4  formula + release      │ (V4's last check needs V3)
                             ├──► V5  rules + R0 ──────┬─────┼──► V7  rule change flow
                             └──► V6  local store ─────┤     │
              UI:       V8  trail + Why + health  (starts after V1a, merges after V2)
                             └──────────────────────► V9  History + Rules tabs (after V5, V6, V8)
```

V3, V4, V5 and V6 can all run in parallel once V2 has merged. V7 and V9 can run
in parallel.

---

## Done
- S1 ✅ 2026-10-15 · docs/spikes/S1-global-hooks.md · changed D9 D11 · body: git show 5b41ac1:docs/BOARD.md
- S2 ✅ 2026-10-15 · docs/spikes/S2-tamper.md · changed D1 D2 D3 D4 D5 D8 D19 · body: git show 5b41ac1:docs/BOARD.md
- S4 ✅ 2026-10-16 · docs/spikes/S4-trail.md · changed D15, V8 · body: git show 5b41ac1:docs/BOARD.md (before the 2026-10-16 screenshot edit)
- S3 ✅ 2026-10-16 · docs/spikes/S3-rule-fit.md · changed D10 D13, V5 · body: git show d0f403b:docs/BOARD.md

## Spikes (steps and pass rules are in `docs/SYNTHESIS.md` §3)

### S5 · G4 · Smoke test: does a brief reach the agent at all (n = 2)
- **Owner:** lead (you at the keyboard)
- **Lane:** lead, after S2 (it reuses `/tmp/af-fresh`)
- **Time box:** 60 min (30 for the brief, 30 for the hook dump).
- **May touch:** `/tmp/af-fresh/` (Makefile, `.cursor/rules/`, `.cursor/hooks.json`);
  a throwaway dump script under `/tmp/af-spike/`; new `docs/spikes/S5-brief.md`.
- **Done when** `docs/spikes/S5-brief.md` has:
  - the brief text;
  - for each of the four chats, the commands before the first passing run,
    taken from the hook log;
  - whether the agent mentioned the brief;
  - the `additional_context` result, if tried;
  - the S2 (d) re-run: `sudo -v` in Terminal, then within a minute
    `sudo -n true; echo exit=$?` in an agent chat;
  - **hook dump (added 2026-10-16):** a passive hook (always allows) on every
    event in Cursor's hooks docs for the installed version (the owner counts
    21), plus one made-up event name. It logs the event name, the input's key
    names, and only the id fields (`conversation_id`, `generation_id`,
    `tool_use_id`, any parent or subagent id); never values of content,
    prompt, reply, `tool_input`, `output` or `edits`. Then one chat that
    starts one foreground and one background subagent, each reading a file
    and running `ls`. Report: which events fire, whether a subagent gets a new
    `conversation_id`, any field linking it to the parent, and whether the
    made-up event name stops the other hooks. These facts settle S3's
    subagent recommendation and the D9 revisit.

  The report states that n = 2 per arm measures nothing about value. A pass only
  unlocks the pre-registered A/B (D16).

---

## v1 cards

### V1a · Rewrite SPEC.md and AGENTS.md for the decisions approved so far
- **Owner:** worker-docs (owner, 2026-10-16); the lead verifies and merges
- **Lane:** docs, ∥ S3
- **Depends on:** D1–D12, D14, D15, D17–D20 approved (2026-10-16)
- **May touch:** `SPEC.md`, `AGENTS.md`; `HOOKS.md` and `README.md` (SPEC
  references only); `docs/product-goals.md` (G1 target flow only, per D6 and
  D20); new `docs/archive/SPEC-hackathon.md` (`git mv` of today's SPEC); new
  `docs/reports/V1a.md`. Not `docs/DECISIONS.md`, `BOARD.md`, `STATE.md`, and
  no code or tests.
- **Done when:**
  - SPEC.md is the v1 spec, built only from approved decisions. What S3 and S5
    can still change (rule kinds and fields, plain-language drafting, G4,
    subagent taint, the sudo grace-period note, the event list) is marked
    "Pending S3" or "Pending S5" with one line on what is open.
  - Section 4 is still "what is stored and how commands are cleaned", so
    HOOKS.md's "SPEC §4" references stay true.
  - AGENTS.md says SPEC.md is the v1 target and the code is moving there card
    by card: inside your card, follow SPEC and the card; outside it, leave the
    code and note the gap in your report; if SPEC and your card disagree, stop
    and ask. It keeps today's commands (V2 changes them), adds hatchling and the
    bundled Python runtime (D5) to approved dependencies, rewords the rule
    shape per D10, replaces the hook-helper "unreachable → allow" rule with the
    D4 offline guard, and its Testing list names only tests that exist (no R0
    line, no "helper drops content" line: V5 and V2 add them).
  - The report has a table mapping each approved decision to its SPEC section,
    and lists every place where today's code differs from the new SPEC.
  - The AGENTS.md check command passes.

### V1b · Fill in what S3 and S5 decided
- **Owner:** lead
- **Lane:** lead
- **Depends on:** S3, S5, D13 and D16 answered
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
  Runs ∥ S3 and S5 (owner, 2026-10-16).
- **Depends on:** V1a
- **May touch:** `pyproject.toml`, `uv.lock`; AGENTS.md "Commands" section and
  README commands (only to keep them true after the move); `recorder/**` → `agentfly/recorder/**`
  (routes split into `agentfly/recorder/api/*.py`, with an explicit router list
  in `app.py`); `hooks/hook.py` → `agentfly/hook_client.py`;
  `recorder/hook_passthrough.py`; new `agentfly/cli/__init__.py` (dispatcher
  that discovers `agentfly/cli/commands/*.py`); new
  `agentfly/cli/commands/serve.py`; `fake_agent.py`; `tests/**`. Not `ui/**`,
  and not `install.sh`.
- **Isolation (machine is shared with S5):** tests and manual runs never use
  port 8787 or the real home folder: a temporary HOME and a free port (for
  example 8797) for every recorder V2 starts. Never touch
  `~/.config/flightrecorder`, `~/.cursor`, `/Library/Application Support/` or
  `/tmp/af-*`.
- **Done when:**
  - **Package.** Distribution name `agentfly-recorder`, build backend
    hatchling (D6). `uv build` makes a wheel that contains `ui/dist`. Installing it
    with `uv tool install` under a temporary HOME puts `agentfly` and
    `agentfly-hook` on PATH. `agentfly serve` runs the recorder (terminal output
    pasted).
  - **Agent argument (D18).** The client is called as
    `agentfly-hook <agent> <event>`; only `cursor` is implemented, and a small
    step normalizes its input. An unknown agent prints allow JSON, exits 0 and
    warns on stderr (test).
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
- **First step, on your Mac (skip if S5's dump settled it):** add one made-up event name to `hooks.json` and
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
- **Depends on:** V2, S3 ✅
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
  - **S3 additions (D10, 2026-10-16):** flag-variant patterns (`--data*`, `=`
    forms, clustered short flags), `path_scope = "outside_workspace"`,
    `pipe_into`, and `scope`/`window` on `after_then` (subagent option (a),
    pending S5). The 10 S3 rules in `docs/spikes/S3-rules.toml` (v0.1 form of
    5, 8 and 14) load, and their inline tests pass with `agentfly rules test`
    (output pasted).
  - **Every rule ships with bypass tests**, not only its own positive tests
    (owner, 2026-10-16): spellings that mean the same action must also match.
    For example, for an upload rule: `curl --data=@f`, `--data-binary @f`,
    `-d@f`, `-sd @f`, long, short and `=` forms, and the same inside
    `bash -c`, `env` and `sudo`. Each bundled rule and each S3 rule has them.
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
- **Lane:** UI. Starts after V1a and merges after V2 (for the `/health` count).
- **Depends on:** S4 ✅, V1a; V2 for the merge
- **May touch:** `ui/src/**` except `ui/src/history/**` and `ui/src/rules/**`;
  `ui/dist` (rebuilt); ui tests. No Python. No new npm dependencies without
  your approval.
- **Done when:**
  - The home trail works on a 500-step mock session: routine runs are grouped,
    blocks, warnings and secret reads are never grouped (repeated identical
    blocks stay separate rows), and Follow still works (tests and a screenshot).
  - It works at half-screen, about 700 px wide: the header stays on one line
    and the Why card stays usable (screenshot at 700 px). From S4.
  - The Why card can be hidden and resized. Propose how in the PR before
    building it (S4: the owner asked; the mechanism is not decided).
  - **Live check before the switch** (the owner asked, 2026-10-16). Build the
    trail first at a non-home address (for example `/?view=trail`); today's
    page stays home. With the recorder running, the owner watches the trail
    while `uv run python fake_agent.py` replays the R1 scenario, and again
    during one real Cursor chat that reads `.env` and then tries a send to
    `https://example.invalid`: new steps appear without a reload, Follow keeps
    up, the block pins and its Why card opens. Only after the owner's yes does
    the commit land that makes the trail home and moves the lane graph to a
    "Graph" tab. The PR records the owner's answer and a screenshot. Needs
    the owner at the keyboard.
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
- **Plain-language rule drafting:** not in v1 (D13 = C). After V5, S3's 10
  sentences are re-run on the candidate models before a card is added.
- **Per-project `agentfly init`:** deferred (D20).
