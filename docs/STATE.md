# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-18 21:12 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: wave-3-merged. S1–S5, V1a, V2, V8, V2b ✅ (2026-10-16); V1b ✅ 65936a1, V5a ✅ 75c7c0e, V6 ✅ 4d31e3d, V3a ✅ 3fdf2f1 (2026-10-18). Main check: 1978 passed, 4 skipped (live Neo4j). Nothing in flight; next wave not yet chosen.
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`).
- Ready to brief: V3b (start/stop/status, LaunchAgent, doctor; plus package-hash check before sudo, owner 2026-10-18), V5b (rules file, kinds, D11 answers, rules CLI, /api/rules; plus R0 guards AgentFly's install folder, owner 2026-10-18), V2c (`tool_use_id` merge + duplicate-read proposal; lead's D9 review first), V8b (recorder fields; check what V2b/V6 already send). V3b ∥ V5b both touch `agentfly/install/` (V5b: rules step of init -g): declare a merge point or sequence it. V2c and V8b share the step record, memory.py, store.py: one after the other.
- V4 on hold: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 installs only from a tap. Rework V4's checks before briefing.
- Briefs: agent-ready-tickets with a fresh pass 2; no pass 3 (owner 2026-10-18). Start workers with `claude --permission-mode plan` and line 1 of the brief.
- Merge rule (learnings): trial-merge parallel cards and probe cross-card behaviour; merge worker branches with `--no-commit` and keep main's STATE/BOARD.

## In flight
none

## Machine state (verified 2026-10-18 21:08 CEST)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent (V3a installed, then uninstalled). Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` has agentfly-recorder 0.1.0 (`~/.local/bin/agentfly`, `agentfly-hook`) from V3a's manual checks; it predates the V3a follow-ups. Reinstall from main before any new manual check.
- Recorder: NOT running (nothing on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). After V6, Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main, plus ag-v1b-spec, ag-v3a-install, ag-v5a-r0-normalize, ag-v6-localstore (all merged; removable on the owner's word; each holds a .venv). Disk: 6.5 GiB free (it filled up once on 2026-10-18).
- Git: origin/main = 274a50b; every later commit is local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute; `.claude/settings.json` denies `git push`.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Next wave: lead proposes V3b ∥ V5b (install-folder overlap declared), then V2c, then V8b. V4 needs its checks reworked first.
2. Remove the four merged worktrees (frees disk): yes or no.
3. Push main to origin when ready (about 27 local commits after 274a50b).

## Decisions changed since last handoff (b8ca2b1)
- D14 note (owner 2026-10-18): Neo4j opt-in via config.toml; R0 denies `wipe`; wipe never clears marks.
- D21 note (owner 2026-10-18): the workspace fallback mark expires after 30 minutes.
- Owner 2026-10-18: R0 keeps the raw-text check (commit messages naming guard paths are denied); root runs user-writable code during sudo → V5b guards the install folder, V3b checks the package hash before sudo; V3/V5 split into a/b; V1b to a worker; staged merge.

## Open risks and findings
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- Same-step "read .env + curl": Cursor may check the curl before the read (the curl cannot carry the content); add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up (restart after init/uninstall).
- R0 gaps (V5a): `pkill python`/`killall python3` can kill the recorder (V3b KeepAlive restarts it); ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md predates V6/V3a in places; Neo4j Session lacks workspace_root; marks inherited through D21 are not derivable from stored steps.
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2c; SPEC §8 "Duplicates" still open.
- Push block is a guard, not a lock · docs/learnings.md.

## Next 3 actions
1. On the owner's wave choice: V3b and V5b briefs (agent-ready-tickets, pass 2), worktrees, plan-mode start commands.
2. D9 review, then the V2c brief; V8b after it.
3. Rework V4's checks (local tap, CLT or a CI runner) and ask the owner.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
