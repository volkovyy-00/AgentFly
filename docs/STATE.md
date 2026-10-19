# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-19 20:10 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: V3c-V8b-merged-pushed. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V6, V6b, V8, V8b, F3, F5, F6 ✅ (BOARD Done; last merges V8b 9b2e00e, V3c 07a8d7f; trial c71d5d3 = main tree, 3× 3419 passed, 5 skipped, 365–410 s each).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a was not red-teamed: a conformance/test-strength review stays open.
- Order (owner 2026-10-19): F7 → V5b ∥ F9 → F8 (alone) → V5c (shares `agentfly/install/` and the CLI with V5b) → V7 ∥ V9. One fix card for the real /code-review findings plus the V3c/V8b leftovers runs alongside F7 if their files do not overlap (F7 owns `tests/` infrastructure). V8b's highlighted verdict comes from V5b.
- Briefs: F7 (pass 2 + brainstorm-advisor, 2026-10-19; written against 252b86c, re-check against 07a8d7f before dispatch). V5b, V5c (pass 2, 2026-10-18; re-check before dispatch). V7, V9, F8, F9, the fix card: not written. F8 needs first: count pyright basic-mode errors; check whether pyright downloads Node on first run. Standing rule: the lead writes or re-checks each brief with agent-ready-tickets and a fresh pass-2 reviewer before every dispatch; the owner says "go". Dispatch with `docs/roles/dispatch.sh <card> <slug>`.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. F7's CI runner may give V4 a place for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check, lead review (a fresh reviewer per branch), merge with `--no-commit`, keep main's STATE/BOARD. From D26 (after F7's CI is green on main a few times): `merge/<batch>` branch, owner pushes and opens a PR, green → lead `git merge --ff-only`, owner pushes main. Before every trial merge once F7 lands: `git fetch`, then the push run for origin/main's exact SHA must be green (no finished run = unknown).

## In flight
none

## Machine state (verified 2026-10-19 20:20 CEST)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` agentfly-recorder 0.1.0 is an old branch build (V3b); reinstall from main before any manual check. No AgentFly LaunchAgent (launchctl list empty for agentfly); harmless override `dev.agentfly.v3bprobe54766 => enabled` stays.
- Recorder: not running (no listener on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main only. V3c and V8b worktrees and branches removed after merge; their worker sessions can be closed. Disk 29 GiB free.
- Git: origin/main = 56cfe66 (owner pushed 2026-10-19 ~20:15); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4): allow ruff/pytest/npm ui checks and gh run list/view, pr view/checks; ask on core.hooksPath; deny git push, --no-verify, commit -n, gh writes (api, auth, pr create/merge/edit/close/comment/review, issue, repo, release, secret, variable, workflow, run rerun/cancel/delete), Read ~/.config/agentfly. Guards, not locks.
- GitHub (owner 2026-10-19): Actions → fork PR workflows "Require approval for all external contributors". No `.github/workflows` yet.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Say "go" for F7 after the lead's re-check of its brief against main.

## Decisions changed since last handoff (252b86c; earlier: git show 252b86c:docs/STATE.md)
- Owner 2026-10-19: V3c same-version rebuild whose files match their own RECORD → ask, not stop; no message advises deleting the root record.
- Owner 2026-10-19: F7 before V5b. CI on main pushes and PRs only, macOS only; a red main blocks merges.
- Owner 2026-10-19: F8 pyright (approved dev dependency), F9 CodeQL (default setup, owner click) + Dependabot (alerts, security, Actions updates only; no uv/npm version-update PRs), after F7.
- Owner 2026-10-19: D26 approved: B (batch PR, lead fast-forwards main, owner pushes), in force after F7's CI is green on main a few times.
- Owner 2026-10-19: settings.json gh limits (above). V3c and V8b merged.
- Still standing from earlier: verify the 7 /code-review findings after the merge, one fix card for the real ones.

## Open risks and findings
- /code-review high 2026-10-19 (one pass, unverified): flag_marked queues on every marked event (V6b); `sudo agentfly uninstall` leaves the LaunchAgent (V3b); memory.replace order and evicted blocked step, merge waiting deque holds id-carrying halves (V2c); mark() runs twice per shell event; uninstall hint twice; memory.clear clears the merger.
- V3c leftovers (fix card): the same-version question names no files (it is the only control for a rewritten RECORD; list the first paths); `_editable` reads direct_url.json without a link check; a linked folder inside the env gets an "outside the environment" message. Later cards: a `.pth` runs in the checking process (root-side verification); R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a `.venv` dist-info); offline guard has no package-command rule; root runs bundled 3.12 against the env's site-packages.
- V8b leftovers (fix card): wrong-token /health test relies on millisecond order; localstore docstring. UI card: ui/README.md and useTrail comment about `?limit=1`. V5b: the rule is looked up twice per hook.
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- Same-step "read .env + curl": Cursor may check the curl before the read; add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up.
- R0 gaps (V5a): `pkill python` can kill the recorder (KeepAlive restarts it); ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md has no `/api/sessions` contract (V9); Neo4j Session lacks workspace_root. No card owns SPEC §10's per-session hash check.
- V2c leftovers: `StrReplace`/`Delete` edits not merged as writes; merge state lost on restart; a blocked step keeps its first half's order.
- Test suite 6–7 min serial (3,419 tests); F7 addresses it.

## Next 3 actions
1. The lead re-checks F7's brief against 07a8d7f (references, premise), then the owner says "go" and dispatches it.
2. Verify the 7 /code-review findings plus the V3c/V8b leftovers → write one fix card (brief + pass 2); dispatch alongside F7 only if its files do not overlap F7's.
3. Then: re-check V5b's brief; move AGENTS.md "Testing" to tests/README.md.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
