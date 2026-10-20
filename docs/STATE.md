# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-20 08:30 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: F7-merged. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V6, V6b, V8, V8b, F3, F5, F6, F7 ✅ (BOARD Done; last merge F7 ae5dd0e = trial 368ab22 tree, 3× 3504 passed, 5 skipped, 111–131 s each).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19): V5b ∥ F9 → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9. One fix card for the real /code-review findings plus the V3c/V8b/F7 leftovers, alongside V5b if files do not overlap. V8b's highlighted verdict comes from V5b.
- Briefs: F10 (pass 2 2026-10-20). V5b, V5c (pass 2, 2026-10-18; re-check before dispatch). V7, V9, F8, F9, F11, F12: not written. F11 (sessions.json off the hook path) after V5b; F12 (links inside the tool env) after V5c; both approved by the owner 2026-10-20. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run; F7's `tests/test_ci_workflow.py` pins ci.yml strictly (one command per `run:`, allow-listed actions and inputs), so F8/F9 edit that test on purpose. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>`.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI now runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (now ~2 min each), a fresh reviewer per branch, fixes back to the worker, merge with `--no-commit`, keep main's STATE/BOARD, check merged tree = trial tree. D26 (batch PR, lead `--ff-only`, owner pushes) starts after CI is green on main a few times. Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green (no finished run = unknown).

## In flight
none

## Machine state (verified 2026-10-20 08:28 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly launchd job; harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Recorder: not running (no listener on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees and branches: main only. Disk 27 GiB free. F7 worker session can be closed.
- Git: origin/main = b84e2ca (owner pushed 2026-10-20); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1 git push origin main`). Remote F7 branch deleted. PR #6 shows "merged" (GitHub marked it when main got its head commit). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks, gh run list/view, pr view/checks; deny git push, --no-verify, commit -n, gh writes, Read ~/.config/agentfly. Guards, not locks.
- GitHub: `.github/workflows/ci.yml` on main since ae5dd0e (push to main, pull requests; macos-15). First main run 39380422658 on ae5dd0e: green (1 of the few D26 needs). Fork PR workflows need approval (owner 2026-10-19).
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Say "go" to dispatch F10; yes/no on the two proposed cards (tool-env links; sessions.json save).

## Decisions changed since last handoff (e48d7ee; earlier: git show e48d7ee:docs/STATE.md)
- Owner 2026-10-19: workers close with /final-verification then /code-review high (docs/reports/README.md).
- Lead 2026-10-20 (F7): two test suites run at once on one Mac can pick the same port (~1% per overlapping pair; a flake, not a false green); no lock file. Clock scan stays perf_counter/monotonic only.
- F7 merged; CI on main pushes and PRs is live.

## Open risks and findings
- /code-review high 2026-10-19 (one pass, unverified): flag_marked queues on every marked event (V6b); `sudo agentfly uninstall` leaves the LaunchAgent (V3b); memory.replace order and evicted blocked step, merge waiting deque holds id-carrying halves (V2c); mark() runs twice per shell event; uninstall hint twice; memory.clear clears the merger.
- V3c leftovers (fix card): the same-version question names no files (list the first paths); `_editable` reads direct_url.json without a link check; a linked folder inside the env gets an "outside the environment" message. Later cards: a `.pth` runs in the checking process; R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a `.venv` dist-info); offline guard has no package-command rule; root runs bundled 3.12 against the env's site-packages.
- V8b leftovers (fix card): wrong-token /health test relies on millisecond order; localstore docstring. UI card: ui/README.md and useTrail comment about `?limit=1`. V5b: the rule is looked up twice per hook.
- F7 leftovers (fix card candidates): `test_package.py::run_uv` skips all 8 package tests on a network error (CI stays green; fail when `CI` is set?); hook-client tests vs a real recorder rely on the 0.5 s wait (watch arm64); Check is one chained CI step (a ruff failure hides test results); uv and Node float in CI (pin needs owner's say); YAML-subset parser reads Unicode spaces differently from GitHub (false alarm, not a miss).
- Tracked `result` symlink in repo root (c190bc6 "demo flos") points into /nix/store (home-manager), dangles, breaks cp/rsync; public repo. Fix card.
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- Same-step "read .env + curl": Cursor may check the curl before the read; add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up.
- R0 gaps (V5a): `pkill python` can kill the recorder; ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md has no `/api/sessions` contract (V9); Neo4j Session lacks workspace_root. No card owns SPEC §10's per-session hash check.
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; merge state lost on restart; a blocked step keeps its first half's order.

## Next 3 actions
1. F10 (fix card) brief ready 2026-10-20 (docs/briefs/F10.md, pass 2 done, uncommitted; lead accepted the uninstall clause: tell the root child by `-I -S`, no new sudo flag). Verified and dropped: flag_marked re-queue (by design); mark() twice (wasted work); memory.clear and /health test fine. Proposed own cards: links inside the tool env (packages.inspect); sessions.json save+fsync on every hook, never pruned (61 ms median at 5000 chats).
2. Re-check V5b's brief against main; dispatch V5b (and the fix card if files do not overlap) on the owner's go.
3. Then: F9 brief; move AGENTS.md "Testing" to tests/README.md.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
