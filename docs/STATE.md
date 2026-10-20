# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-20 12:25 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: F10-V5b-dispatched. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V6, V6b, V8, V8b, F3, F5, F6, F7 ✅ (BOARD Done; last merge F7 ae5dd0e = trial 368ab22 tree, 3× 3504 passed, 5 skipped, 111–131 s each).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19/20): F10 ∥ V5b (in flight) → F9 → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9; F11 after V5b (shares `sessions.py`, `app.py`); F12 after V5c (shares `agentfly/install/`). V8b's highlighted verdict comes from V5b.
- Briefs: F10 (pass 2 against b84e2ca), V5b (pass 2 against dd44029; owner 2026-10-20: a shell warn's `ask` adds "If the user skips this, do not retry with another tool or language."). F9 (pass 2 against 333f665; dispatch after F10 and V5b merge, once the owner's settings are on and a CodeQL run on main has finished). V5c (pass 2, 2026-10-18; re-check before dispatch). V7, V9, F8, F11, F12: not written. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run. `tests/test_ci_workflow.py` pins ci.yml strictly (one command per `run:`, allow-listed actions and inputs), so F8/F9 edit that test on purpose. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>`; the owner starts each worker.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (~2 min each; no other suite running while timed), a fresh reviewer per branch, fixes back to the worker, merge with `--no-commit`, keep main's STATE/BOARD, check merged tree = trial tree. F10 and V5b: merge the first to finish, then trial the second on top (expected conflicts: `tests/test_package.py`, AGENTS.md "Testing", SPEC.md). D26 (batch PR, lead `--ff-only`, owner pushes) starts after CI is green on main a few times (3 so far). Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green.

## In flight
- F10 · Claude Code worker · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-f10-review-fixes · ag-f10-review-fixes · docs/reports/F10.md · docs/briefs/F10.md
- V5b · Claude Code worker · /Users/volkovyy/Projects/AgentFly/.claude/worktrees/ag-v5b-rules-file · ag-v5b-rules-file · docs/reports/V5b.md · docs/briefs/V5b.md

## Machine state (verified 2026-10-20 11:05 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent (as of 08:28). Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly launchd job (08:28); harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Recorder: not running (no listener on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees and branches: main; ag-f10-review-fixes (from d536d39) and ag-v5b-rules-file (from df617fe), both uv synced, workers running (owner 11:14). F10 reported done 12:05 (head 461d8a9, code fed7426); lead trial-merging. V5b: 1 commit (cebe720), running. Disk 27 GiB free.
- Git: origin/main = 3316ee3 (owner pushed 2026-10-20); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1 git push origin main`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks, gh run list/view, pr view/checks; deny git push, --no-verify, commit -n, gh writes, Read ~/.config/agentfly. Guards, not locks.
- GitHub: ci.yml on main since ae5dd0e. Main push runs green: 39380422658 (ae5dd0e), 39396576611 (b84e2ca), 39398305268 (3316ee3). Fork PR workflows need approval (owner 2026-10-19).
- GitHub security settings (owner 2026-10-20 ~11:50): Dependabot alerts on, security updates on (grouped off), auto-triage 1 rule (GitHub preset), malware alerts off, CodeQL default setup on (first scan running).
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
none

## Decisions changed since last handoff (b84e2ca; earlier: git show b84e2ca:docs/STATE.md)
- Owner 2026-10-20: F10 dispatched (fix card); F11 and F12 approved as cards.
- Owner 2026-10-20: V5b dispatched alongside F10; a shell warn's `ask` answer has the rule text in both messages and `agent_message` adds "If the user skips this, do not retry with another tool or language."
- Lead 2026-10-20 (verified by running): flag_marked re-queue is by design; mark() twice per shell event is wasted work only; memory.clear and the wrong-token /health test are fine. F10 takes the rest.

## Open risks and findings
- F9: Dependabot raises no alerts for SHA-pinned actions; `uv.lock` is covered (SBOM: 29 pkg:pypi = uv.lock, owner ran it 2026-10-20); the bundled CPython (D5) has no alert source; npm security-update PRs will fail the stale-build check (lead folds them into a card).
- V3c later-card items: a `.pth` runs in the checking process (root-side verification); R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a `.venv` dist-info); offline guard has no package-command rule; root runs bundled 3.12 against the env's site-packages.
- UI card: ui/README.md and useTrail comment about `?limit=1` (V8b).
- F7 leftovers: hook-client tests vs a real recorder rely on the 0.5 s wait (watch arm64); Check is one chained CI step (a ruff failure hides test results); uv and Node float in CI (pin needs the owner's say); `UV is None` skip in tests/test_package.py stays green on CI; two suites at once on one Mac can share a test port (~1%, accepted).
- Same-step "read .env + curl": Cursor may check the curl before the read; add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up.
- R0 gaps (V5a): `pkill python` can kill the recorder; ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md has no `/api/sessions` contract (V9); Neo4j Session lacks workspace_root. No card owns SPEC §10's per-session hash check.
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; merge state lost on restart; a blocked step keeps its first half's order.

## Next 3 actions
1. When a worker reports: `head -n 6` of its report, update STATE; trial-merge, fresh reviewer, fixes back to the worker, merge.
2. Trial the second of F10/V5b on top of the first; resolve the expected conflicts in the trial, not on main.
3. Then: F9 brief; move AGENTS.md "Testing" to tests/README.md; re-check V5c's brief after V5b merges.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
