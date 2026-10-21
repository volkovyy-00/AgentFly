# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-21 11:30 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: F10-merged. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V6, V6b, V8, V8b, F3, F5, F6, F7, F10 ✅ (BOARD Done; last merge F10 5239e96 = trial 74acb5b tree, 3× 3529 passed, 5 skipped, 143–206 s with V5b's worker running).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19/20): V5b (fix round) → F9 ∥ F13 ∥ F11 (owner 2026-10-20: F11 in wave 1) → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9; F12 after V5c and F13 (shares `agentfly/install/`, `packages.py`). V8b's highlighted verdict comes from V5b.
- Briefs: V5b (pass 2 against dd44029; owner 2026-10-20: a shell warn's `ask` adds "If the user skips this, do not retry with another tool or language."). F9 (pass 2 against 333f665; owner settings on and CodeQL green on main, so it waits only for V5b's merge). F13 (pass 2 against f6bc22b; after V5b). V5c (pass 2, 2026-10-18; D27/D28 and V5b's npm dodges added 2026-10-20; full re-check after V5b merges). F11 (pass 2 against trial 686ccbb, 2026-10-20; re-check after V5b merges; slug `session-state`). V7, V9, F8, F12: not written. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run. `tests/test_ci_workflow.py` pins ci.yml strictly, so F8/F9 edit that test on purpose. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>` (F9 `security-scans`, F13 `escape-names`); the owner starts each worker.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (~2–3 min each; no other suite running while timed), a fresh reviewer per branch, fixes back to the worker, merge with `--no-commit`, keep main's STATE/BOARD, check merged tree = trial tree. Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green.
- D26 B is now in force (CI green on main 4×): V5b is the first batch. The lead builds `merge/<batch>` from main with the card merge only; the owner pushes it and opens one PR; green → lead `git merge --ff-only merge/<batch>` on main, handoff commit, owner pushes main. Red → drop the branch, worker fixes.

## In flight
- V5b · Claude Code worker (fix round 2 done 2026-10-21, head 549cec1) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5b-rules-file · ag-v5b-rules-file · docs/reports/V5b-fix2.md · docs/briefs/V5b-fix2.md

## Machine state (verified 2026-10-20 13:40 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly launchd job; harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Recorder: not running (no listener on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees and branches: main; ag-v5b-rules-file (66 commits, head 549cec1 = fix2 report); trial worktree `.claude/worktrees/trial-v5b` (detached 9169ed6 = main 0e34261 + 549cec1; union of appended tests in test_install_cli.py). Disk 25 GiB free.
- Git: origin/main = b342323 (owner pushed 2026-10-20 ~12:23; carries F10); lead commits after it are local only (owner pushes with `! AGENTFLY_ALLOW_PUSH=1 git push origin main`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks, gh run list/view, pr view/checks; deny git push, --no-verify, commit -n, gh writes (owner runs `gh run rerun`), Read ~/.config/agentfly. Guards, not locks.
- GitHub CI green on main: 39398305268 (3316ee3), 39407614953 (b342323: attempt 1 red on a timing flake, attempt 2 green, 3529 passed). CodeQL b342323 green. Fork PR workflows need approval (owner 2026-10-19).
- GitHub security settings (owner 2026-10-20 ~11:50): Dependabot alerts on, security updates on (grouped off), auto-triage 1 rule (GitHub preset), malware alerts off, CodeQL default setup on.
- No Xcode CLT (`make` opens a dialog).

## Waiting on owner
none

## Decisions changed since last handoff (3316ee3; earlier: git show 3316ee3:docs/STATE.md)
- Owner 2026-10-21 (worker session, V5b-fix2 Task 6b): command lists count against the per-hook rules limit; an unfinished highlight is skipped (brief amended).
- Owner 2026-10-20: D27 changed (R1: no floating folder patterns; structural check). D30 (uninstall keeps an edited rules.toml; V5c) approved; V5b gets a second fix round (docs/briefs/V5b-fix2.md, incl. the long-word crash) before merging.
- Owner 2026-10-20: D29 (keep a chat's session note 29 idle days; marked chats, their parents and links kept) approved.
- Owner 2026-10-20: D27 (a rules file cannot drop or weaken R1) and D28 (`init -g` refreshes an unedited rules file) approved; V5b fixes go to a fresh worker; plan + subagent-driven-development for workers rejected.
- Owner 2026-10-20: F10 merged (5239e96), pushed; F13 approved (escape names in package-check messages).

## Open risks and findings
- CI flake: `test_offline_guard.py` silent recorder took 1.28 s on macos-15 once (b342323); recurs → fix card. F7, V2c, UI-card leftovers: git show 0e34261:docs/STATE.md.
- F9: Dependabot raises no alerts for SHA-pinned actions; the bundled CPython (D5) has no alert source; npm security-update PRs will fail the stale-build check (lead folds them into a card).
- F10 leftovers: AGENTS.md "Testing" lines for package tests failing (not skipping) under CI and the hand-typed-sudo uninstall path (lead, after V5b); SPEC §10 lacks the "service was not touched" message; `CI=false` counts as CI in `tests/test_package.py`.
- V3c later-card items: `.pth` runs in the checking process; R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a dist-info); no offline-guard package rule; root runs bundled 3.12 on the env's site-packages.
- Missing interpreter: exit 127, fails open; missing client: exit 2, deny-all.
- R0 gaps (V5a): `pkill python`; ruby/perl -e; relative paths after `cd`, globs, braces, variables; ~/.claude/settings.json unguarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md lacks `/api/sessions` (V9); Neo4j Session lacks workspace_root; no card owns SPEC §10's per-session hash check.
- V5b-fix2 leftovers (report 549cec1; re-trial reviewers add: `_project_relative` realpath per long word, `_command_hit` program walk uncharged, FLOAT_STEPS unpinned, installer `lock_problems` refuses a trusted 0640 edited rules.toml): CR1 sessions.py: a fallback-linked subagent misses a parent's later R1 mark (custom rules only) → F11 brief. A3: root-owned 0600 edited rules.toml: `init -g` says kept, recorder runs the default → V5c brief. An inherited trigger on a heavy command gets a spurious limit deny (fails closed). Command-list charge up to ~4x conservative. CR4, CR8–CR10, M5, M7 listed. `_ALARMS` drops highlighted steps (page card). Pre-existing on main until V5b merges: a shell word >255 chars → hook 500 → offline guard.

## Next 3 actions
1. V5b re-trial 9169ed6: 3× green (4480 passed, 200–218 s, reviewers running); 3 fresh reviewers MERGE. Lead timings (idle): default rules, 300 words of 1,022-char paths 633 ms (>0.5 s wait → offline guard; main falls to it on one 256-char word); 198-rule list file 3,000 words 439 ms. Owner: merge now + follow-up card, or fix round 3.
2. If clean: SPEC §7/§8 and HOOKS.md edits on merge; drop `docs/superpowers/*V5b-fix2*` (owner 2026-10-20); build `merge/v5b`, owner pushes and opens the PR; on green `--ff-only` main and hand off. Leftovers → V5c brief.
3. Then dispatch F9 and F13 on the owner's go; add F10's AGENTS.md Testing lines; move AGENTS.md "Testing" to tests/README.md; re-check V5c's brief.

Rehearsals: Grok 4.7 High in Cursor.
