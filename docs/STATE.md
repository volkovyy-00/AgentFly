# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-21 16:35 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: wave1-merged. S1–S5, V1a, V1b, V2, V2b, V2c, V3a, V3b, V3c, V5a, V5b, V5d, V6, V6b, V8, V8b, F3, F5, F6, F7, F9, F10, F11, F13 ✅ (BOARD Done; last merge: wave 1 via PR #8, merge/wave1 0ad2eac fast-forwarded onto main; trial 3× 4673 passed, 5 skipped; PR CI and CodeQL green).
Pending decisions: D16

## Spikes and cards
- Done cards: one line each under BOARD `## Done`. V5a not red-teamed (conformance review open).
- Order (owner 2026-10-21): D31 move (lead with the owner) → F15 cleanup → F8 (alone) → V5c → V7 ∥ V9; F12 after V5c; F14 any time.
- Briefs: V5c (pass 2 2026-10-18; re-check against main, add A3 + D30). F8, F12, F14, F15, V7, V9: not written; F8 first counts pyright basic-mode errors and checks pyright's Node download. Standing rule: brief via agent-ready-tickets + fresh pass 2, owner says "go", `docs/roles/dispatch.sh <card> <slug>`, owner starts each worker.
- Worker closing rule (owner 2026-10-19, docs/reports/README.md): `/final-verification` on main...HEAD, commit, then `/code-review high`; verdict in the report.
- V4 on hold: this Mac is x86_64 with no Xcode CLT. CI runs on GitHub's macos-15 (arm64); V4 may use a runner for its checks; rework then.
- Merge: trial-merge in a scratch worktree, 3× full check (~2.5–3.5 min each; no other suite running while timed), a fresh reviewer per branch, fixes back to the worker, check merged tree = trial tree. Before every trial merge: `git fetch`, then the push run for origin/main's exact SHA must be green.
- D26 B: the lead commits STATE, then builds `merge/<batch>` from main with the card merges only (no main commits until it lands); the owner pushes it and opens one PR; green → `git merge --ff-only merge/<batch>`, handoff commit, owner pushes main. A red CodeQL gate on path look-ups: read the check-run annotations, the owner dismisses.

## In flight
none

## Machine state (verified 2026-10-21 16:30 CEST unless marked)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- Recorder: not running (owner had the lead run `agentfly stop` 2026-10-21 16:40 on the old V3b-build service started 16:10; no listener on 8787, no launchd job, plist removed). The offline guard applies in this repo's Cursor while it is down. `uv tool` agentfly-recorder 0.1.0 is still the old V3b wheel: reinstall from main before any manual check. Harmless override `dev.agentfly.v3bprobe54766 => enabled` stays (as of 2026-10-19).
- Files (as of 2026-10-19; the lead may not read ~/.config/agentfly): ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly. Neo4j off (no config.toml). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main; merged and kept until the owner says remove: ag-f9-security-scans, ag-f13-escape-names, ag-f11-session-state, ag-v5d-long-commands, ag-v5b-rules-file (with git-ignored `.superpowers/sdd/`, 1.1 MB). Local branch merge/wave1 = main. Remote `merge/v5b`, `merge/wave1` the owner may delete. Disk 17 GiB free.
- Git: origin/main = 3871787 (owner pushed 2026-10-21 16:58; PR #8 marked merged); CI 39621577693 and CodeQL 39621577847 queued on it. Lead commits after it are local. Owner pushes with `! AGENTFLY_ALLOW_PUSH=1 git push origin main`. Origin is PUBLIC. core.hooksPath absolute. `.claude/settings.json` (441ddd4) allows checks and gh reads, denies push, --no-verify, gh writes; a `gh api` GET was denied 2026-10-21 (the owner runs those with `!`).
- CI: PR #8 check 39613747155 green (2m37s); main 0473d58 green (39583473122). History: git show 41fcc24:docs/STATE.md. Fork PR workflows need approval (owner 2026-10-19).
- GitHub security (owner 2026-10-20): Dependabot alerts and security updates on, auto-triage GitHub preset, CodeQL default setup on; `.github/dependabot.yml` (F9) now on main. CodeQL #5–#7 and PR #8's two `clean.py` path alerts dismissed by the owner 2026-10-21.
- No Xcode CLT (`make` opens a dialog).

## Waiting on owner
1. Create an empty private GitHub repo for D31 (any name); then the move starts with the lead.

## Decisions changed since last handoff (41fcc24; earlier: git show 41fcc24:docs/STATE.md)
- Owner 2026-10-21: D31 approved (process docs to a private repo; public tree only, no history rewrite); starts now that wave 1 is merged.
- Owner 2026-10-21: CR1 sub-case is its own card F14; F15 (hackathon cleanup) per D31.
- Lead 2026-10-21: V5d per-hook disk look-up budget (words past it stored as `<arg>`), its extra store-less cases, F13's escaping of NBSP/ZWJ, F9's `tests/test_ci_workflow.py` edit, D29's "marked" read as effective marks (F11 fix round), F9 squashed.

## Open risks and findings
- CI flake: `test_offline_guard.py` silent recorder took 1.28 s on macos-15 once (b342323); recurs → fix card. F7, V2c, UI-card leftovers: git show 0e34261:docs/STATE.md.
- Dependabot raises no alerts for SHA-pinned actions; the bundled CPython (D5) has no alert source; npm security-update PRs will fail the stale-build check (lead folds them into a card). vite 8.3.2 advisory had no alert (→ F15).
- F10 leftovers: SPEC §10 lacks the "service was not touched" message; `CI=false` counts as CI in `tests/test_package.py` (AGENTS.md Testing lines → F15).
- V3c later-card items: `.pth` runs in the checking process; R0 false positives (`uv tool … --with ./x`, `brew upgrade --dry-run`, `ls` of a dist-info); no offline-guard package rule; root runs bundled 3.12 on the env's site-packages.
- R0 gaps (V5a): `pkill python`; ruby/perl -e; relative paths after `cd`, globs, braces, variables; ~/.claude/settings.json unguarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md lacks `/api/sessions` (V9); README/HOOKS/AGENTS "Hook facts" still say the session file is written on every hook (F11); Neo4j Session lacks workspace_root; no card owns SPEC §10's per-session hash check.
- V5b leftovers: V5c gets A3 (root 0600 edited rules.toml: said kept, recorder runs the default) + D30. Spurious limit deny for an inherited trigger on a heavy command (fails closed). CR4, CR8–CR10, M5, M7 (V5b-fix2 report). `_ALARMS` drops highlighted steps (page card).
- V5d leftovers: free program look-ups are per clause (198 clauses ≈ 130 ms unmetered, admin-written files only); deep shared prefix then a different middle folder re-walks (~200 ms CPU for 300 words). F11: `links.json` not fsynced (crash-safe, not power-loss).

## Next 3 actions
1. Check CI on 3871787 is green; then the D31 move with the owner (private repo, lead tools, `git rm` from the public tree).
2. F15 brief (after the move), then V5c re-check with A3 + D30.
3. F8 prep: count pyright basic-mode errors; check pyright's Node download.

Rehearsals: Grok 4.7 High in Cursor.
