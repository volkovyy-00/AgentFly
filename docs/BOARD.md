# AgentFly v1 board (revision 3)

Status: **spikes S1–S5, V1a and V2 are done; V8 is done; V2b is in flight (2026-10-16).
D16 and D21–D24 are open.** V2 was split into V2 and V2b; V2b's duplicates half is V2c.
Cards with a file in `docs/briefs/` take that brief as authoritative. After
approval, any card whose plan depends on a decision you changed is rewritten
before it starts.

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
Spikes        Lead (your machine): S1 ──► S2 ──► S5 ✅
              Backend:             S3              (∥ S1, S2)
              UI:                  S4              (∥ S1, S2)

              ─────────── you approve DECISIONS.md ───────────

v1            Docs:     V1a ✅ (worker) ──► Lead: V1b (after S5)
              Backend:  V2 ✅ ┬──► V2b ──┬──► V3  CLI install commands ──┐
                             │          └──► V5  rules + R0 ──────┐     │ (V4's last check needs V3)
                             ├──► V4  formula + release           ├─────┼──► V7  rule change flow
                             └──► V6  local store ────────────────┘     │
                                        V2b ──► V2c  step merge + read-dedup proposal (∥ V3, V5)
              UI:       V8 ✅ trail + Why + health
                             ├──► V8b recorder fields for V8 (backend, after V2b)
                             └──────────────────────► V9  History + Rules tabs (after V5, V6, V8)
```

V2b, V4 and V6 run in parallel once V2 has merged; V3, V5 and V2c once V2b has.
V7 and V9 can run in parallel.

---

## Done
- S1 ✅ 2026-10-15 · docs/spikes/S1-global-hooks.md · changed D9 D11 · `cursor-agent` half not tested, accepted by the owner 2026-10-16 · body: git show 5b41ac1:docs/BOARD.md
- S2 ✅ 2026-10-15 · docs/spikes/S2-tamper.md · changed D1 D2 D3 D4 D5 D8 D19 · body: git show 5b41ac1:docs/BOARD.md
- S4 ✅ 2026-10-16 · docs/spikes/S4-trail.md · changed D15, V8 · body: git show 5b41ac1:docs/BOARD.md (before the 2026-10-16 screenshot edit)
- S3 ✅ 2026-10-16 · docs/spikes/S3-rule-fit.md · changed D10 D13, V5 · body: git show d0f403b:docs/BOARD.md
- S5 ✅ 2026-10-16 · docs/spikes/S5-brief.md · pass (smoke test; D16 open); findings for D9, S3 subagents, V3, V1b · body: git show f0d68e3:docs/BOARD.md
- V1a ✅ 2026-10-16 · docs/reports/V1a.md · merged b7f7192 · changed D5 D9 D10 D14 (review answers) · body: git show b7f7192:docs/BOARD.md
- V2 ✅ 2026-10-16 · docs/reports/V2.md · merged 3da6dc7 · accepted edits outside Touches (setup_credentials.sh, .env.example, AGENTS.md paths); `ls -la` → `ls -l<arg>` per SPEC § 4 · body: git show ba74ffe:docs/BOARD.md
- V8 ✅ 2026-10-16 · docs/reports/V8.md · merged 92e7fdc (part 1) and 4af8125 (home switch: trail at /, lane graph at /?view=graph) · GIF dropped by the owner; real Cursor chat check passed · body: git show f786847:docs/BOARD.md

## Spikes (steps and pass rules are in `docs/SYNTHESIS.md` §3)

(S5 done; see Done.)

---

## v1 cards

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

### V2b · Hardened hook client: never fails, fixed port, strips everything, offline guard
- **Owner:** worker-backend · **Brief (authoritative):** `docs/briefs/V2b.md`
- **Lane:** backend, after V2 merges; ∥ V4 and V6.
- **Depends on:** V2 ✅
- Owner's priority order (2026-10-16): never exits non-zero on any input (offline
  guard on unreadable input, fuzz tests); port fixed at 8787 (D25); nested stripping; install.sh paths.

### V2c · One step per action: `tool_use_id` merge, duplicate-read proposal
- **Owner:** worker-backend · brief to write after V2b and the D9 review
- **Lane:** backend, after V2b; ∥ V3, V5.
- **Depends on:** V2b
- Split from V2b 2026-10-16 (brief budget). A `preToolUse` and a `beforeShellExecution`
  call with the same `tool_use_id` show as one step in `/api/steps`; the report proposes
  (does not build) the merge key for duplicate file reads (D9 note), with fixture evidence.

### V3 · CLI install commands: `init -g`, `uninstall`, `doctor`, `start`, `stop`, `status`
- **Owner:** worker-backend
- **Lane:** backend, ∥ V4, V5 and V6 after V2
- **Depends on:** V2, V2b, S1, S2
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
- **Depends on:** V2, V2b (Write target path for R0), S3 ✅
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
    - `agentfly serve`, `agentfly stop`, `agentfly uninstall` and `brew services`
      for AgentFly (owner, 2026-10-16: a second `serve` rotated the token and
      switched protection off);
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
  - The hook client's offline guard (V2b) is run against the same
    normalisation cases and must agree on every outbound one (SPEC § 9).
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

### V8b · Recorder fields for the Why card and health strip
- **Owner:** worker-backend · brief to write
- **Lane:** backend, after V2b; ∥ V3, V4, V6.
- **Depends on:** V2b (it adds the offline-guard count to `/health`), V8 (field names)
- **May touch:** the recorder's step record, `/api/steps` and `/health`; tests.
- **Done when:** each step on `/api/steps` carries `rule_text`, `user_message`
  and `agent_message` when a rule fired, and the `highlighted` verdict when a highlight rule fired, and `/health` carries `last_hook_at`
  and `offline_guard_count`, under the names V8's page reads; nothing stored
  gains content (SPEC §4); the route whitelist test is unchanged.

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
