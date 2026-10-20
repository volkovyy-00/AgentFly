# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-20 15:40 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: F10-merged. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V6, V6b, V8, V8b, F3, F5, F6, F7, F10 ✅ (BOARD Done; last merge F10 5239e96 = trial 74acb5b tree, 3× 3529 passed, 5 skipped, 143–206 s with V5b's worker running).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19/20): V5b (reported done, fe3386e) → F9 ∥ F13 → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9; F11 after V5b (shares `sessions.py`, `app.py`); F12 after V5c and F13 (shares `agentfly/install/`, `packages.py`). V8b's highlighted verdict comes from V5b.
- Briefs: V5b (pass 2 against dd44029; owner 2026-10-20: a shell warn's `ask` adds "If the user skips this, do not retry with another tool or language."). F9 (pass 2 against 333f665; owner settings on and CodeQL green on main, so it waits only for V5b's merge). F13 (pass 2 against f6bc22b; after V5b). V5c (pass 2, 2026-10-18; re-check before dispatch). V7, V9, F8, F11, F12: not written. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run. `tests/test_ci_workflow.py` pins ci.yml strictly, so F8/F9 edit that test on purpose. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>` (F9 `security-scans`, F13 `escape-names`); the owner starts each worker.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (~2–3 min each; no other suite running while timed), a fresh reviewer per branch, fixes back to the worker, merge with `--no-commit`, keep main's STATE/BOARD, check merged tree = trial tree. Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green.
- D26 B is now in force (CI green on main 4×): V5b is the first batch. The lead builds `merge/<batch>` from main with the card merge only; the owner pushes it and opens one PR; green → lead `git merge --ff-only merge/<batch>` on main, handoff commit, owner pushes main. Red → drop the branch, worker fixes.

## In flight
- V5b · Claude Code worker · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5b-rules-file · ag-v5b-rules-file · docs/reports/V5b.md · docs/briefs/V5b.md

## Machine state (verified 2026-10-20 13:40 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly launchd job; harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Recorder: not running (no listener on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees and branches: main; ag-v5b-rules-file (13 commits, head fe3386e = report); trial worktree `.claude/worktrees/trial-v5b` (detached 686ccbb = main 522b0b4 + V5b; remove after the fix round). Disk 25 GiB free.
- Git: origin/main = b342323 (owner pushed 2026-10-20 ~12:23; carries F10); lead commits after it are local only (owner pushes with `! AGENTFLY_ALLOW_PUSH=1 git push origin main`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks, gh run list/view, pr view/checks; deny git push, --no-verify, commit -n, gh writes (owner runs `gh run rerun`), Read ~/.config/agentfly. Guards, not locks.
- GitHub CI green on main: 39380422658 (ae5dd0e), 39396576611 (b84e2ca), 39398305268 (3316ee3), 39407614953 (b342323: attempt 1 red on a timing flake, attempt 2 green, 3529 passed). CodeQL b342323 green. Fork PR workflows need approval (owner 2026-10-19).
- GitHub security settings (owner 2026-10-20 ~11:50): Dependabot alerts on, security updates on (grouped off), auto-triage 1 rule (GitHub preset), malware alerts off, CodeQL default setup on.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Close the V5b worker session; after the V5b-fix brief passes pass 2, say go and start the fix worker by hand in `.claude/worktrees/ag-v5b-rules-file`.

## Decisions changed since last handoff (3316ee3; earlier: git show 3316ee3:docs/STATE.md)
- Owner 2026-10-20: D27 (a rules file cannot drop or weaken R1) and D28 (`init -g` refreshes an unedited rules file) approved; V5b fixes go to a fresh worker; plan + subagent-driven-development for workers rejected.
- Owner 2026-10-20: GitHub security settings on (above). `uv.lock` is in GitHub's dependency graph (SBOM: 29 pkg:pypi), so Python alerts need no extra step; question closed.
- Owner 2026-10-20: F10 merged (5239e96) and pushed; F13 approved as a card (escape names in package-check messages).
- Lead 2026-10-20: F10's two 5 s hang guards without `@wallclock` accepted (they catch a hang, not a time limit).

## Open risks and findings
- CI flake: `tests/test_offline_guard.py` "silent recorder" test bounds 8-way parallel hook-client starts (0.1 s budget) under 1.0 s; one took 1.28 s on macos-15 (b342323 attempt 1). If it recurs: fix card (bound or load), not a hook-client change.
- F9: Dependabot raises no alerts for SHA-pinned actions; the bundled CPython (D5) has no alert source; npm security-update PRs will fail the stale-build check (lead folds them into a card).
- F10 leftovers: AGENTS.md "Testing" lines for package tests failing (not skipping) under CI and the hand-typed-sudo uninstall path (lead, after V5b); SPEC §10 lacks the "service was not touched" message; `CI=false` counts as CI in `tests/test_package.py`.
- V3c later-card items: a `.pth` runs in the checking process (root-side verification); R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a `.venv` dist-info); offline guard has no package-command rule; root runs bundled 3.12 against the env's site-packages.
- UI card: ui/README.md and useTrail comment about `?limit=1` (V8b).
- F7 leftovers: hook-client tests vs a real recorder rely on the 0.5 s wait (watch arm64); Check is one chained CI step (a ruff failure hides test results); uv and Node float in CI (pin needs the owner's say); two suites at once on one Mac can share a test port (~1%, accepted).
- Same-step "read .env + curl": Cursor may check the curl before the read; add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up.
- R0 gaps (V5a): `pkill python` can kill the recorder; ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md has no `/api/sessions` contract (V9); Neo4j Session lacks workspace_root. No card owns SPEC §10's per-session hash check.
- V5b: trial 686ccbb 3× green (3871 passed, 5 skipped, 137–162 s); 3 fresh reviewers, no blocker; fixes in docs/briefs/V5b-fix.md (fresh worker on the same branch and worktree, started by hand; report docs/reports/V5b-fix.md).
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; merge state lost on restart; a blocked step keeps its first half's order.

## Next 3 actions
1. V5b-fix brief: pass-2 reviewer running; then owner closes the V5b session, says go, starts the worker by hand in the V5b worktree.
2. After the fix: re-trial, 3× check, reviewer; SPEC §7/§8 edits on merge; build `merge/v5b`, owner pushes and opens the PR; on green `--ff-only` main and hand off.
3. Then dispatch F9 and F13 on the owner's go; add F10's AGENTS.md Testing lines; move AGENTS.md "Testing" to tests/README.md; re-check V5c's brief.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
