# AgentFly v1 board (revision 3)

Status (2026-10-19): **spikes S1–S5 and V1a, V1b, V2, V2b, V2c, V3a, V3b, V5a, V6, V6b, V8,
F3, F5, F6 done and merged (see Done). In flight: V3c ∥ V8b. Next: V5b → V5c, then V7 ∥ V9;
V4 on hold (no Xcode CLT on this Mac). D16 is the only open decision.** V2 was split into V2 and
V2b (its duplicates half is V2c); V3 and V5 into a/b/c cards.
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

Wave 3 (owner, 2026-10-18): V3a, V5a, V6 and V1b in parallel; post-merge review → fix cards F3 ∥ F5 ∥ F6. Then V3b ∥ V2c (V2c ✅ 2026-10-19); V6b ∥ V3b; then V3c, V5b, V5c (owner 2026-10-19: no parallel rules lane)
one after the other (owner 2026-10-18: they share `agentfly/install/` and the CLI; V5b split into V5b + V5c, V3c split from
V3b). V8b after V6b (they share the step record, `memory.py` and `store.py`).
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
- V3a ✅ 2026-10-18 · docs/reports/V3a.md · merged 3fdf2f1 · Intel x86_64 build; Cursor 3.24.12 and 3.25.9 (exact list); R1 10/10 sandboxed and not; hook client strips subagentStart.task · body: git show 8b1258a:docs/BOARD.md
- F5 ✅ 2026-10-18 · docs/reports/F5.md · merged 4310f97 · offline guard covers file targets (D4 note); marks only get stricter · body: git show 2ad871e:docs/BOARD.md
- F6 ✅ 2026-10-18 · docs/reports/F6.md · merged 61bb9a3 · history marked = R1; wipe bounded 10 s; purge cuts WAL; flaky test (no flush) in test_localstore folded into V2c (owner 2026-10-18) · body: git show 2ad871e:docs/BOARD.md
- F3 ✅ 2026-10-18 · docs/reports/F3.md · merged 83f8e7b · uninstall stop points exit 0 or 127; failed restore keeps old Python in `.old-*`, path printed (accepted by the owner 2026-10-18) · body: git show 2ad871e:docs/BOARD.md
- V2c ✅ 2026-10-19 · docs/reports/V2c.md · merged fb72286 · one step per action (id merge, path fallback); flaky history test fixed; history "marked" gap for edit steps accepted → V6b (owner 2026-10-19) · body: git show e2da26b:docs/BOARD.md
- V3b ✅ 2026-10-19 · docs/reports/V3b.md · merged ba6f488 · start/stop/status (own LaunchAgent or brew services), doctor (12 lines), guards cover dev.agentfly.recorder, homebrew.mxcl.agentfly, sh.brew.agentfly; `stop` deletes the plist; lead review fixed doctor `path`, Homebrew `start`, uninstall message · body: git show e1d4aeb:docs/BOARD.md
- V6b ✅ 2026-10-19 · docs/reports/V6b.md · merged a9b753f · history stores the marked flag (chat) and marking step (step); a fallback chat that later marks itself names that step (SPEC §4) · body: git show e1d4aeb:docs/BOARD.md
- V8b ✅ 2026-10-19 · docs/reports/V8b.md · merged 9b2e00e · steps carry rule_text and the deny's messages (memory only), /health last_hook_at, ?all=1 marked_order; 2 low test/doc leftovers → fix card; UI notes (ui/README, useTrail comment) → UI card · body: git show 441ddd4:docs/BOARD.md
- V3c ✅ 2026-10-19 · docs/reports/V3c.md · merged 07a8d7f · package check before sudo (links, extra files, own RECORD), same-version rebuild and upgrade ask (owner 2026-10-19), root -I -S -B on bundled Python, R0 guards tool env and uv/pipx/brew, doctor package line; leftovers → fix card · body: git show 441ddd4:docs/BOARD.md
- F7 ✅ 2026-10-20 · docs/reports/F7.md · merged ae5dd0e · pytest-xdist check 37–44% of serial; ci.yml (main pushes and PRs, macos-15, read-only, SHA-pinned) pinned by tests/test_ci_workflow.py; CI green on arm64 (PR #6); leftovers → fix card · body: git show ae5dd0e:docs/BOARD.md

## Spikes (steps and pass rules are in `docs/SYNTHESIS.md` §3)

(S5 done; see Done.)

---

## v1 cards

### V4 · Homebrew formula and release workflow
- **Owner:** worker-backend
- **Lane:** backend, after V2. Its last check needs V3b.
- **Depends on:** V2 (for the brew-services check, V3b ✅)
- **From V3b (2026-10-19):** Homebrew `stop` must also stop a leftover `dev.agentfly.recorder` (V3b review); pin the formula's launchd label (Homebrew 7 names it `sh.brew.agentfly`, D8 names `homebrew.mxcl.agentfly`; both are guarded).
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
  - V3b ✅: `brew services start agentfly` serves `/health`
    (output pasted).
  - The release workflow builds the UI once and makes the wheel and sdist. It
    has no publish step until you approve publishing.

### V5b · Rules file and severities: R1 in TOML, warn and highlight, `rules check` / `rules test`, `GET /api/rules`
- **Brief:** `docs/briefs/V5b.md` (authoritative; pass 2 against dd44029) · dispatched 2026-10-20 (worktree ag-v5b-rules-file, from df617fe), alongside F10. Split from V5 (owner 2026-10-18). "Block npm publish after .env" ships in the default rules (owner 2026-10-18).
- **Lane:** backend, after V3c · **Depends on:** V5a ✅, V3a ✅, F5 ✅, V3b, V3c

### V5c · S3 rule additions and the owner's ten rules, with bypass tests
- **Brief:** `docs/briefs/V5c.md` (authoritative). Split from V5b (owner 2026-10-18). The ten S3 rules ship as an example file, off by default (owner 2026-10-18).
- **Lane:** backend, after V5b · **Depends on:** V5b

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

### F10 · Review fixes: uninstall, package check, step merge
- **Owner:** worker-backend · brief docs/briefs/F10.md (pass 2 2026-10-20, against b84e2ca) · dispatched 2026-10-20 (worktree ag-f10-review-fixes, from d536d39); may run alongside V5b (no shared files except new tests in tests/test_install_cli.py)
- **Scope:** findings the lead verified 2026-10-20: uninstall service message under hand-typed sudo and single restart hint; same-version question names files; direct_url.json regular-file check; merge waiting slot freed on id join; evicted alarm in `flagged`; package tests fail on a network error under CI; `git rm result`. Not: links inside the tool env, sessions.json save per hook (own cards, proposed).
- **Done when:** the brief's acceptance criteria hold.

### F11 · Session state off the hook path
- **Owner:** worker-backend · brief not written · after V5b (shares `sessions.py` and `app.py`) · approved by the owner 2026-10-20
- **Scope:** `SessionStore.save` rewrites and fsyncs all of `sessions.json` inside every `/hook` answer, and nothing prunes it (lead measured 2026-10-20: `put()` 1.3 ms at 10 chats, 61 ms median at 5000). Settle what must be on disk before the answer (marks; `next_step`, since `steps` rows are `INSERT OR REPLACE` on (session_id, ord)), and add retention like D14.
- **Done when:** a hook answer no longer waits on a whole-file rewrite; marks and step order survive a crash and a restart; the file stays bounded.

### F12 · Package check: linked folders inside the tool environment
- **Owner:** worker-backend · brief not written · after V5c (shares `agentfly/install/`) · approved by the owner 2026-10-20
- **Scope:** `agentfly/install/packages.py` § `inspect` resolves the whole site-packages path, so a linked folder between the environment root and site-packages is either reported as "outside the environment" or not at all (SPEC §7: a file behind a linked folder inside the environment is a mismatch).
- **Done when:** any linked folder from the environment root down is a named mismatch, and the wording names the link.

### F8 · Type checking: pyright
- **Owner:** worker-backend · brief not written · after F7; alone, not alongside V5b (fixing type errors touches all of `agentfly/`)
- **Scope (owner 2026-10-19: pyright approved):** before the brief, the lead counts basic-mode errors and checks how the pyright package gets its Node runtime (a first-run download would put the network in the check command; `pyright[nodejs]` would be a new dependency to ask about). Pyright in dev deps and AGENTS.md "Approved dependencies", basic mode, existing errors fixed (not silenced wholesale), a step in `ci.yml` and AGENTS.md's check command.
- **Done when:** pyright clean locally and in CI; F7's `ci.yml` test covers the new step.

### F9 · Security scans: CodeQL and Dependabot
- **Owner:** the owner (repo settings) + worker for one YAML file · after F7
- **Scope (owner 2026-10-19: CodeQL and Dependabot yes; alerts, security updates and Actions updates only, no uv/npm version-update PRs):** CodeQL default setup (an owner click in repo settings: no workflow file, no write permission in our workflows; runs on GitHub's Linux runners, which "macOS only" does not cover; it is a scanner, not the test CI). Dependabot alerts and security updates (settings) plus `.github/dependabot.yml` for GitHub Actions version updates only; no uv/npm version-update PRs (they bypass the lead and fail the stale-build check); `@xyflow/react` and `motion` stay pinned. Dependabot PRs are never merged on GitHub: the lead folds them into a card.
- **Done when:** a CodeQL run on main and the alert settings on; findings triaged (fixed, or a later card).

## Not on the board (on purpose)
- **Publishing to PyPI and the Homebrew tap:** the lead does it, after your OK
  on each release. It is outward-facing.
- **G4 pre-registered A/B (4-memory-claude.md):** added only if S5 passes and
  V6 exists. It also needs `afterShellExecution` exit codes (D9).
- **Plain-language rule drafting:** not in v1 (D13 = C). After V5, S3's 10
  sentences are re-run on the candidate models before a card is added.
- **Per-project `agentfly init`:** deferred (D20).
