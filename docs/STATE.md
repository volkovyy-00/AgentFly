# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-18 22:50 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: fix-cards-dispatched. S1–S5, V1a, V2, V8, V2b ✅ (2026-10-16); V1b ✅ 65936a1, V5a ✅ 75c7c0e, V6 ✅ 4d31e3d, V3a ✅ 3fdf2f1 (2026-10-18). Main check: 1978 passed, 4 skipped. Post-merge review → F3 ∥ F5 ∥ F6 running (owner started them 2026-10-18).
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`).
- Fix cards first: F3 (uninstall can leave exit 2 = deny-all; foreign escaped entries; backups lost), F5 (offline guard allows Read/Write of token, sessions.json, config.toml; observe() can clear a fallback mark), F6 (history shows unmarked after `bash -c 'cat .env'`/`curl -d@.env`; wipe hangs ~139 s on a busy DB; purged rows linger in WAL; CLEAN_COMMANDS=0 reaches history). V5a was not red-teamed: a conformance/test-strength review stays open.
- Ready to brief after fixes: V3b (start/stop/status, LaunchAgent, doctor; plus package-hash check before sudo, owner 2026-10-18), V5b (rules file, kinds, D11 answers, rules CLI, /api/rules; plus R0 guards AgentFly's install folder, owner 2026-10-18), V2c (brief `docs/briefs/V2c.md` ready, pass 2 done; scope per D9 merge-rule note, owner 2026-10-18: merge by `tool_use_id` for every kind, path fallback only for id-less 3.24.12 reads; after F6 and the owner's 3.25.9 capture), V8b (recorder fields; check what V2b/V6 already send). V3b ∥ V5b both touch `agentfly/install/` (V5b: rules step of init -g): declare a merge point or sequence it. V2c and V8b share the step record, memory.py, store.py: one after the other.
- V4 on hold: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 installs only from a tap. Rework V4's checks before briefing.
- Briefs: agent-ready-tickets with a fresh pass 2; no pass 3 (owner 2026-10-18). Start workers with `claude --permission-mode plan` and line 1 of the brief.
- Review evidence: probes from the 2026-10-18 review live in the lead's scratchpad (ephemeral); re-run against F-branches before merging: subagentStart-only link denies; uninstall interrupted after client unlink must exit 127 not 2; `bash -c 'cat .env'` then curl → history marked; offline Read/Write/Delete of token denied.
- Merge rule (learnings): trial-merge parallel cards and probe cross-card behaviour; merge worker branches with `--no-commit` and keep main's STATE/BOARD.

## In flight
- F3 · worker · .claude/worktrees/ag-f3-install-fixes · ag-f3-install-fixes · docs/reports/F3.md
- F5 · worker · .claude/worktrees/ag-f5-guard-fixes · ag-f5-guard-fixes · docs/reports/F5.md
- F6 · worker · .claude/worktrees/ag-f6-history-fixes · ag-f6-history-fixes · docs/reports/F6.md

## Machine state (verified 2026-10-18 21:08 CEST; worktrees and disk 22:50)
- /Library/Application Support/AgentFly, /Library/Application Support/Cursor/hooks.json, ~/.cursor/hooks.json: absent (V3a installed, then uninstalled). Repo .cursor/hooks.json: present (dev wiring; doubles events if `init -g` is also installed).
- `uv tool` has agentfly-recorder 0.1.0 (`~/.local/bin/agentfly`, `agentfly-hook`) from V3a's manual checks; it predates the V3a follow-ups. Reinstall from main before any new manual check.
- Recorder: NOT running (nothing on 8787). The offline guard applies in this repo's Cursor while it is down. Start: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token), ~/.local/share/agentfly (logs, sessions.json). After V6, Neo4j gets nothing without `neo4j = true` in ~/.config/agentfly/config.toml (absent). AuraDB as of 2026-10-16: Session 51, Step 98; owner: leave it.
- Worktrees: main plus the three F worktrees. The four merged ones were removed on the owner's word (2026-10-18); their branches are kept. Disk: 4.5 GiB free while F workers run (it filled up once on 2026-10-18).
- Git: origin/main = b6e51cc (owner pushed 2026-10-18 22:55); later commits are local only (owner pushes with `AGENTFLY_ALLOW_PUSH=1`). Origin repo is PUBLIC. core.hooksPath absolute; `.claude/settings.json` denies `git push`.
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Before V2c starts: on Cursor 3.25.9 with the recorder up, one chat doing a file write, an edit, two parallel reads and one @-attached file (hook log captures it).

## Decisions changed since last handoff (b8ca2b1)
- D4 note (owner 2026-10-18): the offline guard also denies Read, Write and Edit of guard paths (F5 builds it, SPEC §9).
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
- One action recorded as two steps · V2c. On 3.25.9 `beforeReadFile` carries `tool_use_id` (28/28 match); SPEC §8 and AGENTS.md hook facts say otherwise until V2c.
- Push block is a guard, not a lock · docs/learnings.md.

## Next 3 actions
1. On the owner's wave choice: V3b and V5b briefs (agent-ready-tickets, pass 2), worktrees, plan-mode start commands.
2. Dispatch V2c after F6 merges and the owner's capture (commit the D9 note and brief first); V8b after V2c.
3. Rework V4's checks (local tap, CLT or a CI runner) and ask the owner.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
