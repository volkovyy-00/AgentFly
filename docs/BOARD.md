# AgentFly v1 board (revision 3)

Status: **spikes S1–S5, V1a, V2, V8 and V2b are done (2026-10-16). Wave 3
(V3a, V5a, V6) briefed 2026-10-18; V3 and V5 were split into a/b halves.
D16 is the only open decision.** V2 was split into V2 and V2b; V2b's duplicates half is V2c.
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
  - route registration in `agentfly/recorder/app.py` (and one store line in
    § `apply_rules`, owned by V5a, for V6);
  - `ROUTE_WHITELIST` in `tests/test_app.py`;
  - command registration in `agentfly/cli/__init__.py`.

  Both are shared on purpose: every new route has to be added consciously
  (D19).
- **CLI.** Each subcommand is its own module in `agentfly/cli/`, next to
  `serve.py`. V2's dispatcher does not discover modules: each command adds one
  import and one registration line to `agentfly/cli/__init__.py` (a merge point).
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

v1            Docs:     V1a ✅ ──► V1b SPEC catch-up (worker, ∥ wave 3)
              Backend:  V2 ✅ ┬──► V2b ✅ ┬──► V3a install ──► V3b service + doctor ─┐ (V4's last check needs V3b)
                             │          └──► V5a normalise + R0 ──► V5b rules file ─┼──► V7  rule change flow
                             ├──► V4  formula + release                         │
                             └──► V6  local store ──┬──────────────────────────┘
                                                    ├──► V2c  step merge + read-dedup proposal
                                                    └──► V8b  recorder fields for V8
              UI:       V8 ✅ trail + Why + health
                             └──────────────────────► V9  History + Rules tabs (after V5b, V6, V8)
```

Wave 3 (owner, 2026-10-18): V3a, V5a, V6 and V1b in parallel. Then V3b and V5b; V2c and
V8b after V6 (they share the step record, `memory.py` and `store.py`).
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
- V2b ✅ 2026-10-16 · docs/reports/V2b.md · merged 79a46a7 · changed D25 (new); owner addendum: serve port check, 401/403 → guard, all one-liners denied offline, live Neo4j tests need AGENTFLY_TEST_NEO4J_ENV; p95 69 ms accepted until V3 · body: git show 7f7cd70:docs/BOARD.md
- V1b ✅ 2026-10-18 · docs/reports/V1b.md · merged 65936a1 · SPEC catch-up; leaves §8 Duplicates (V2c) · body: git show 8b1258a:docs/BOARD.md
- V5a ✅ 2026-10-18 · docs/reports/V5a.md · merged 75c7c0e · fallback mark expires after 30 min (owner, D21) · body: git show 8b1258a:docs/BOARD.md
- V6 ✅ 2026-10-18 · docs/reports/V6.md · merged 4d31e3d · Neo4j opt-in (config.toml); session events reach the D21 link (follow-up 1bc5aa3) · body: git show 8b1258a:docs/BOARD.md

## Spikes (steps and pass rules are in `docs/SYNTHESIS.md` §3)

(S5 done; see Done.)

---

## v1 cards

### V2c · One step per action: `tool_use_id` merge, duplicate-read proposal
- **Owner:** worker-backend · brief to write after V2b and the D9 review
- **Lane:** backend, after V6 (same recorder files).
- **Depends on:** V2b, V6
- Split from V2b 2026-10-16 (brief budget). A `preToolUse` and a `beforeShellExecution`
  call with the same `tool_use_id` show as one step in `/api/steps`; the report proposes
  (does not build) the merge key for duplicate file reads (D9 note), with fixture evidence.

### V3a · System install: `init -g` and `uninstall`
- **Brief:** `docs/briefs/V3a.md` (authoritative). Split from V3 (owner, 2026-10-18).
- **Lane:** backend, ∥ V5a and V6 · **Depends on:** V2b ✅

### V3b · Service and `doctor`: `start`, `stop`, `status`, `doctor`
- **Owner:** worker-backend · brief to write after V3a merges
- **Lane:** backend, after V3a; ∥ V5b
- **Depends on:** V3a
- **May touch:** new `agentfly/cli/{start,stop,status,doctor}.py`; `agentfly/install/`;
  `agentfly/cli/uninstall.py` (also removes the service); README "Install";
  `tests/test_install_*.py`; the `agentfly/cli/__init__.py` merge point.
- **Done when** (carried from V3):
  - `start`, `stop` and `status` use `brew services` for a Homebrew install and
    AgentFly's own LaunchAgent otherwise; both set `KeepAlive` (D4, D8; the
    brew-services plist is checked once V4 exists).
  - `doctor` is all green after a clean install: hashes recorded by V3a match, the
    bundled Python is not user-writable (D5), `KeepAlive` is set, `agentfly` on `PATH`
    is ours (D6 name clash), the registered events are on the known list and Cursor's
    Hooks log has no "Invalid … config" / "Failed to parse" line for our file (D23),
    and gate hooks in `~/.claude/settings.json` warn, or fail if V3a found an allow
    can override (D24).
  - On your Mac: kill the recorder and launchd restarts it. With `KeepAlive` off, or
    during the gap, `doctor` is red, the offline guard denies `curl`, and the message
    says `agentfly start`. After `agentfly uninstall`, `launchctl list | grep agentfly`
    prints nothing.
  - Before asking for `sudo`, `init -g` and `uninstall` check that the AgentFly package
    about to run as root matches its release hashes, and `doctor` checks the same (owner,
    2026-10-18: root runs user-writable code during `sudo`).

### V4 · Homebrew formula and release workflow
- **Owner:** worker-backend
- **Lane:** backend, after V2. Its last check needs V3b.
- **Depends on:** V2 (for the brew-services check, V3b)
- **May touch:** new `packaging/homebrew/agentfly.rb`, new
  `packaging/homebrew/README.md`, new `.github/workflows/release.yml`. Not the
  README; V3a and V3b own the install section.
- **Done when:**
  - `brew install --build-from-source ./packaging/homebrew/agentfly.rb` and
    `brew test agentfly` pass locally (output pasted).
  - `test do` pipes a fake `beforeShellExecution` payload through
    `agentfly-hook` with no server, and asserts valid JSON.
  - The caveats tell you to run `agentfly init -g`, and to run
    `agentfly uninstall` before `brew uninstall`.
  - After V3b merges: `brew services start agentfly` serves `/health`
    (output pasted).
  - The release workflow builds the UI once and makes the wheel and sdist. It
    has no publish step until you approve publishing.

### V5b · Rules file, rule kinds, warn and highlight, `rules check` / `rules test`, `GET /api/rules`
- **Owner:** worker-backend · brief to write after V5a merges
- **Lane:** backend, after V5a; ∥ V3b
- **Depends on:** V5a ✅; V3a (`init -g` installs the active rules file)
- **May touch:** `agentfly/recorder/rules.py`; new `agentfly/recorder/rulefile.py`;
  packaged `agentfly/rules/default.toml`; new `agentfly/cli/{rules_check,rules_test}.py`;
  new `agentfly/recorder/api/rules.py`; the rules step in `agentfly/install/`;
  `tests/test_rules.py`, new `tests/test_rulefile.py`; the declared merge points.
- **Done when** (carried from V5):
  - R1 and its lists load from the rules file; the active file is root-owned in
    `/Library/Application Support/AgentFly/` (D3) and installed by `init -g`. Every
    existing rule test passes. A rules file that removes or weakens R0 is rejected.
  - S3 additions (D10): flag-variant patterns, `path_scope = "outside_workspace"`,
    `pipe_into`. The 10 S3 rules in `docs/spikes/S3-rules.toml` (v0.1 form of 5, 8
    and 14) load and their inline tests pass with `agentfly rules test` (output
    pasted). The subagent `scope`/`window` is replaced by D21 A, built in V5a.
  - Every bundled and S3 rule ships bypass tests (owner, 2026-10-16).
  - "Block npm publish after reading .env" is added by editing only the rules file:
    a test, plus a diff that touches no `.py` file for it.
  - block, warn and highlight produce the D11 answers (tests). `GET /api/rules` is
    read-only and in the whitelist.
  - R0 also guards AgentFly's own install folder (uv tool / pipx environment and the
    Homebrew keg), so the agent cannot change code that later runs under `sudo` (owner,
    2026-10-18).

### V7 · Rule change flow: draft, check, diff, backtest, `sudo` approve
- **Owner:** worker-backend
- **Lane:** backend, ∥ V9
- **Depends on:** V5b, V6
- **May touch:** new
  `agentfly/cli/{rules_draft,rules_diff,rules_backtest,rules_apply}.py`;
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
  - `ROUTE_WHITELIST` in `tests/test_app.py` is unchanged by this card.
  - Plain-language drafting is not included unless D13 is approved.

### V8b · Recorder fields for the Why card and health strip
- **Owner:** worker-backend · brief to write
- **Lane:** backend, after V6 (same recorder files).
- **Depends on:** V2b (it adds the offline-guard count to `/health`), V8 (field names)
- **May touch:** the recorder's step record, `/api/steps` and `/health`; tests.
- **Done when:** each step on `/api/steps` carries `rule_text`, `user_message`
  and `agent_message` when a rule fired, and the `highlighted` verdict when a highlight rule fired, and `/health` carries `last_hook_at`
  and `offline_guard_count`, under the names V8's page reads; nothing stored
  gains content (SPEC §4); the route whitelist test is unchanged.

### V9 · UI: History and Rules tabs
- **Owner:** worker-ui
- **Lane:** UI, after V8; ∥ V7
- **Depends on:** V5b (`GET /api/rules`), V6 (sessions API), V8
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
