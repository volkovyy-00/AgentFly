# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-18 23:40 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: V2c-dispatched. S1–S5, V1a, V2, V8, V2b ✅ (2026-10-16); V1b, V5a, V6, V3a ✅; F5 ✅ 4310f97, F6 ✅ 61bb9a3, F3 ✅ 83f8e7b (merged 2026-10-18, lead probes 19/19 pass). Main check: 2128 passed, 4 skipped (first run had 1 flaky failure, see risks).
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`).
- Fix cards F3, F5, F6 merged (BOARD Done). V5a was not red-teamed: a conformance/test-strength review stays open.
- Briefs ready (pass 2 done 2026-10-18): V3b `docs/briefs/V3b.md` (service + doctor; next, ∥ V2c), V3c (package check before sudo, R0 guards install folder and blocks reinstalling AgentFly, version-change confirm), V5b (rules file, severities, rules check/test, /api/rules, npm rule in default; lead re-checks against main before dispatch), V5c (S3 additions, ten S3 rules as off-by-default example, bypass tests). Order: V3b → V3c → V5b → V5c (they share `agentfly/install/` and the CLI). V8b after V2c (shares step record, memory.py, store.py); its highlighted verdict comes from V5b.
- V4 on hold: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 installs only from a tap. Rework V4's checks before briefing.
- Briefs: agent-ready-tickets with a fresh pass 2; no pass 3 (owner 2026-10-18). Start workers with `claude --permission-mode plan` and line 1 of the brief.
- Review evidence: the four 2026-10-18 probes re-run on the merged tree (subagentStart-only link, history marks for wrapped/`-d@` reads, offline file tools on token spellings; uninstall stop points via F3's per-call sweep): all pass.
- Merge rule (learnings): trial-merge parallel cards and probe cross-card behaviour; merge worker branches with `--no-commit` and keep main's STATE/BOARD.

## In flight
- V2c · worker · .claude/worktrees/ag-v2c-step-merge · ag-v2c-step-merge · docs/reports/V2c.md

## Machine state (verified 2026-10-18 21:08 CEST; worktrees and disk 22:50)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent (V3a installed, then uninstalled). Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` has agentfly-recorder 0.1.0 (`~/.local/bin/agentfly`, `agentfly-hook`) from V3a's manual checks; it predates the V3a follow-ups. Reinstall from main before any new manual check.
- Recorder: running on 8787 (owner started it for the V2c capture; verified 2026-10-18 after the capture). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). After V6, Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main and ag-v2c-step-merge. The F3/F5/F6 worktrees were removed on the owner's word (2026-10-18); branches kept. Disk as of 23:50: 1.5 GiB free; it filled up once on 2026-10-18.
- Git: origin/main = b6e51cc (owner pushed 2026-10-18 22:55); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute; `.claude/settings.json` denies `git push`.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Start the V2c worker (command in the lead's message of 2026-10-18).
2. Start the V3b worker once its worktree exists (lead creates it on request).

## Decisions changed since last handoff (b8ca2b1)
- D4 note (owner 2026-10-18): the offline guard also denies Read, Write and Edit of guard paths (F5 builds it, SPEC §9).
- D14 note (owner 2026-10-18): Neo4j opt-in via config.toml; R0 denies `wipe`; wipe never clears marks.
- D21 note (owner 2026-10-18): the workspace fallback mark expires after 30 minutes.
- Owner 2026-10-18 (late): V3b ∥ V2c, then V3c → V5b → V5c; V5b split into V5b + V5c; package check and install-folder guard in a new V3c; R0 blocks the agent from installing/upgrading/removing AgentFly and a version change needs the owner's confirm; npm-publish rule in the default; S3 rules ship off by default.
- Owner 2026-10-18: F3's failed restore keeps the old Python in a printed `.old-*` folder (accepted); flaky history test folded into V2c.
- Owner 2026-10-18: R0 keeps the raw-text check (commit messages naming guard paths are denied); root runs user-writable code during sudo → V5b guards the install folder, V3b checks the package hash before sudo; V3/V5 split into a/b; V1b to a worker; staged merge.

## Open risks and findings
- `SessionStore.save` fsyncs sessions.json on every hook in the request handler; no card owns it.
- Same-step "read .env + curl": Cursor may check the curl before the read (the curl cannot carry the content); add to SPEC's known gaps.
- Missing interpreter → exit 127 → Cursor fails open; missing client → exit 2 → deny-all. Cursor reads the system file only at start-up (restart after init/uninstall).
- R0 gaps (V5a): `pkill python`/`killall python3` can kill the recorder (V3b KeepAlive restarts it); ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion and variables unseen; ~/.claude/settings.json not guarded.
- Exact Cursor version list (3.24.12, 3.25.9): `init -g` refuses after each Cursor update until a release adds it.
- HOOKS.md predates V6/V3a in places; Neo4j Session lacks workspace_root; marks inherited through D21 are not derivable from stored steps.
- No card owns SPEC §10's per-session hash check at session start (raised in V3b pass 2).
- Flaky history test (missing flush; failed once in the merged full run, passed on rerun) · V2c fixes it.
- One action recorded as two steps · V2c. On 3.25.9 `beforeReadFile` carries `tool_use_id` (28/28 match); SPEC §8 and AGENTS.md hook facts say otherwise until V2c.
- Push block is a guard, not a lock · docs/learnings.md.

## Next 3 actions
1. Create the V3b worktree (`.claude/worktrees/ag-v3b-service`, branch ag-v3b-service) and give the start command.
2. When V2c or V3b reports: read its head, probe, trial-merge. Then V3c, re-check V5b's brief against main, V5b, V5c.
3. Rework V4's checks (local tap, CLT or a CI runner) and ask the owner.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
