# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-21 12:17 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: V5b-merged. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V5b, V6, V6b, V8, V8b, F3, F5, F6, F7, F10 ✅ (BOARD Done; last merge V5b de0aee7 via PR #7 = trial 9169ed6 tree + lead SPEC/HOOKS edits, 3× 4480 passed, 5 skipped).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19/20/21): F9 ∥ F13 ∥ F11 ∥ V5d (wave 1; V5d's file overlap with F11 checked at its brief) → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9; F12 after V5c and F13 (shares `agentfly/install/`, `packages.py`).
- Briefs: wave 1 dispatched 2026-10-21 (briefs against 41fcc24): V5d (new, fresh pass 2), F9, F13 (re-stamped), F11 (re-stamped; CR1 added to scope and criteria). V5c (pass 2, 2026-10-18; D27/D28 and V5b's npm dodges added 2026-10-20; full re-check after V5b merges; A3 + D30 to add). V7, V9, F8, F12: not written. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run. `tests/test_ci_workflow.py` pins ci.yml strictly, so F8/F9 edit that test on purpose. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>` (F9 `security-scans`, F13 `escape-names`, F11 `session-state`, V5d `long-commands`); the owner starts each worker.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (~2–3 min each; no other suite running while timed), a fresh reviewer per branch, fixes back to the worker, merge with `--no-commit`, keep main's STATE/BOARD, check merged tree = trial tree. Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green.
- D26 B in force (first batch V5b, PR #7). The lead builds `merge/<batch>` from main with the card merge only (no main commits until it lands); the owner pushes it and opens one PR; green → lead `git merge --ff-only merge/<batch>` on main, handoff commit, owner pushes main. Red → drop the branch, worker fixes.

## In flight
- F9 · worker (owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-f9-security-scans · ag-f9-security-scans · docs/reports/F9.md · docs/briefs/F9.md
- F13 · worker (owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-f13-escape-names · ag-f13-escape-names · docs/reports/F13.md · docs/briefs/F13.md
- F11 · worker (owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-f11-session-state · ag-f11-session-state · docs/reports/F11.md · docs/briefs/F11.md
- V5d · worker (owner starts) · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5d-long-commands · ag-v5d-long-commands · docs/reports/V5d.md · docs/briefs/V5d.md
(dispatched 2026-10-21 from main 61e2981; owner started all four workers)
- F9 done 2026-10-21 (4d387ae; 4516 passed): Touches deviation accepted; reviewer MERGE. Squash at merge (OS username in two commits). YAML-reader quirks → F8 brief. One trial merge + one PR (D26 B) for all four.

## Machine state (verified 2026-10-21 12:16 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly launchd job; harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Recorder: not running (no listener on 8787, no launchd job). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees and branches: main; wave 1 (see In flight); ag-v5b-rules-file (merged, head 549cec1) kept with the worker's git-ignored `.superpowers/sdd/` (1.1 MB, advisor analysis and reviews) until the owner says remove; remote `merge/v5b` (PR #7) the owner may delete. Disk 23 GiB free.
- Git: origin/main = 0473d58 (owner pushed 2026-10-21 ~12:16; carries V5b; PR #7 merged); CI 39583473122 and CodeQL 39583470949 green on it (checked 2026-10-21); lead commits after it are local only (owner pushes with `! AGENTFLY_ALLOW_PUSH=1 git push origin main`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks, gh run list/view, pr view/checks; deny git push, --no-verify, commit -n, gh writes (owner runs `gh run rerun`), Read ~/.config/agentfly. Guards, not locks.
- GitHub CI green on main: 39398305268 (3316ee3), 39407614953 (b342323: attempt 1 red on a timing flake, attempt 2 green, 3529 passed). CodeQL b342323 green. PR #7: CI check green; CodeQL's 3 `py/path-injection` alerts (stat-only, pre-existing behaviour) dismissed by the owner (won't fix) → V5d. Fork PR workflows need approval (owner 2026-10-19).
- GitHub security settings (owner 2026-10-20 ~11:50): Dependabot alerts on, security updates on (grouped off), auto-triage 1 rule (GitHub preset), malware alerts off, CodeQL default setup on.
- No Xcode CLT (`make` opens a dialog).

## Waiting on owner
1. F9: dismiss CodeQL #5, #6, #7 in the UI (comments in docs/reports/F9.md on its branch); vite 8.3.2 advisory has no Dependabot alert (check Security → Dependabot → Closed).
2. Create an empty private GitHub repo for D31 (any name) before the move; the move starts after all of wave 1 is merged.

## Decisions changed since last handoff (3316ee3; earlier: git show 3316ee3:docs/STATE.md)
- Owner 2026-10-21: V5b merged (PR #7, CodeQL alerts dismissed); long-command speed and the other re-trial leftovers go to follow-up card V5d.
- Owner 2026-10-21 (worker session, V5b-fix2 Task 6b): command lists count against the per-hook rules limit; an unfinished highlight is skipped (brief amended).
- Owner 2026-10-20: D27 (changed), D28, D29, D30 approved; F10 merged; F13 approved. Details: DECISIONS.md, `git show 41fcc24:docs/STATE.md`.
- Owner 2026-10-21: D31 approved (process docs to a private repo); starts after wave 1 is merged.
- Lead 2026-10-21: V5d per-hook disk look-up budget (words past it stored as `<arg>`); the owner may override.

## Open risks and findings
- CI flake: `test_offline_guard.py` silent recorder took 1.28 s on macos-15 once (b342323); recurs → fix card. F7, V2c, UI-card leftovers: git show 0e34261:docs/STATE.md.
- F9: Dependabot raises no alerts for SHA-pinned actions; the bundled CPython (D5) has no alert source; npm security-update PRs will fail the stale-build check (lead folds them into a card).
- F10 leftovers: AGENTS.md "Testing" lines for package tests failing (not skipping) under CI and the hand-typed-sudo uninstall path (lead, after V5b); SPEC §10 lacks the "service was not touched" message; `CI=false` counts as CI in `tests/test_package.py`.
- V3c later-card items: `.pth` runs in the checking process; R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a dist-info); no offline-guard package rule; root runs bundled 3.12 on the env's site-packages.
- R0 gaps (V5a): `pkill python`; ruby/perl -e; relative paths after `cd`, globs, braces, variables; ~/.claude/settings.json unguarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md lacks `/api/sessions` (V9); Neo4j Session lacks workspace_root; no card owns SPEC §10's per-session hash check.
- V5b leftovers (V5b-fix2 report 549cec1): now in V5d and F11 briefs; V5c: A3 root 0600 edited rules.toml (said kept, recorder runs the default) + D30. Spurious limit deny for an inherited trigger on a heavy command (fails closed). CR4, CR8–CR10, M5, M7 listed. `_ALARMS` drops highlighted steps (page card).

## Next 3 actions
1. Read each wave-1 report's head when the owner says it is ready; trial-merge one at a time.
2. A3 + D30 → V5c brief; re-check V5c against main.
3. After wave 1 merges: D31 move with the owner, then the hackathon-cleanup card; F10's AGENTS.md Testing lines and moving AGENTS.md "Testing" to tests/README.md fold into it.

Rehearsals: Grok 4.7 High in Cursor.
