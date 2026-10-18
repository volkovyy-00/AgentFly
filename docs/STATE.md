# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-18 21:40 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: wave-3 merging. V1b ✅ merged 65936a1, V5a ✅ merged 75c7c0e (check: 1827 passed, 4 skipped). V6 and V3a have follow-ups (staged merge, owner OK 2026-10-18).
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1–S5, V1a, V2, V8, V2b.
- Owner 2026-10-18: V3 split into V3a (init -g, uninstall) and V3b (start/stop/status, doctor); V5 split into V5a (normalisation, D21 subagent mark, R0) and V5b (rules file, kinds, D11 answers, rules CLI, /api/rules). R0 also denies `agentfly wipe`. Neo4j only with `neo4j = true` in ~/.config/agentfly/config.toml (recorded on D14). No pass 3 (oracle) on tickets.
- Briefs: docs/briefs/V3a.md, V5a.md, V6.md (agent-ready-tickets, pass 2 done by fresh subagents). V3b and V5b briefs are written after V3a and V5a merge (their BOARD cards carry the remaining criteria).
- Merge points (BOARD rules): `agentfly/cli/__init__.py` (no discovery; one import + one registration line per command), app.py routes and `apply_rules` (V5a owns; V6 adds one store line), `ROUTE_WHITELIST` in tests/test_app.py. CLI modules live in `agentfly/cli/` next to serve.py.
- After V6: V2c (`tool_use_id` merge + duplicate-read proposal, after the lead's D9 review) and V8b (recorder fields; V2b already reports `offline_guard_count`, check before briefing).
- V1b moved to a worker (owner 2026-10-18), brief docs/briefs/V1b.md. It leaves SPEC §8 "Duplicates" as is (no approved merge key; V2c) and §7 (init -g still installs the rules file in the v1 target; only the card order moved it to V5b).
- V4 not started: this Mac is x86_64 with no Xcode CLT; `brew install --build-from-source` needs CLT, pydantic-core needs Rust, Homebrew 7 needs a tap (not a bare .rb path). Revisit V4's checks before briefing.

## In flight
- V3a · worker (follow-up: merge main, strip subagentStart.task; merges after V6) · .claude/worktrees/ag-v3a-install · ag-v3a-install · docs/reports/V3a.md
- V6 · worker (follow-up: merge main, route session events to the subagent link) · .claude/worktrees/ag-v6-localstore · ag-v6-localstore · docs/reports/V6.md

## Machine state (verified 2026-10-18 17:53 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (`.venv/bin/python hooks/hook.py`). V3a's manual checks move it aside and restore it.
- Recorder: NOT running (nothing on 8787). While it is down, Cursor in this repo denies outbound commands and every `python -c`/`node -e` (offline guard). Start: `uv run agentfly serve`.
- Files (as of 2026-10-16): ~/.config/agentfly (neo4j.env, token, migration marker), ~/.local/share/agentfly/sessions.json. Backup ~/.config/flightrecorder.bak-2026-10-16 (mode 700).
- AuraDB (as of 2026-10-16): Session 51, Step 98. Owner: leave it, no --clear. A running recorder writes there while neo4j.env exists, until V6 merges (then only with `neo4j = true`).
- Worktrees: main plus the three above (created 2026-10-18 from the commit that carries the briefs). Old branches ag-v2-package, ag-v8-trail, ag-v2b-hook-client kept locally (merged).
- Git: core.hooksPath absolute (main's docs/roles/git-hooks). `.claude/settings.json` denies `git push`; the owner pushes with `AGENTFLY_ALLOW_PUSH=1`. origin/main = 274a50b; b8ca2b1 and later are local only. origin branch ag-31-sunset-old-page: already gone (pruned 2026-10-18). Origin repo is PUBLIC.
- /tmp/af-spike, /tmp/af-fresh (as of 2026-10-16); copy in logs/spike/ (gitignored).
- No Xcode Command Line Tools: `make` opens an install dialog.

## Waiting on owner
1. Paste the V6 and V3a follow-ups (given in chat 2026-10-18); after V6 merges, tell V3a to merge main once more.

## Decisions changed since last handoff (b8ca2b1)
- Owner 2026-10-18: staged merge; D21 fallback mark expires after 30 min; root-run risk → R0 guards the install folder (V5b) and a package hash check before sudo (V3b).
- D14 status amended (owner 2026-10-18): Neo4j opt-in via config.toml; R0 denies `wipe`; wipe never clears marks.
- Owner 2026-10-18: R0 keeps the raw-text check as SPEC says, accepting that a commit message naming `hooks.json`, `.config/agentfly` or 8787 is denied; revisit after real use.

## Open risks and findings
- MERGE BUG, fix in V6 follow-up (verified 2026-10-18 by probe on a trial merge V1b+V5a+V6, 1900 tests green): V6's `hook()` answers `sessionStart`/`sessionEnd`/`subagentStart` before `apply_rules`, so V5a's link never sees `subagentStart`; a subagent whose only link is `subagentStart` is allowed the R1 send (V5a alone: deny). Fix in V6 after V5a merges.
- LEAK: hook client keeps `subagentStart.task` (the subagent's prompt text) in the request and the hook log; V3a registers `subagentStart`. Fix in V3a's follow-up before any real install.
- V3a findings: a missing interpreter makes Cursor fail open (exit 127), unlike a missing client (exit 2, deny-all); Cursor reads the system hooks.json only at start-up (restart after init/uninstall); Settings → Hooks does not list system hooks; same-step "read .env + curl" can reach the shell gate before the read (curl can't carry the content); exact Cursor version list (3.24.12, 3.25.9 verified 2026-10-18).
- V5a gaps: `pkill python`/`killall python3` can kill the recorder; ruby/perl -e not inline code; relative paths after `cd`, globs, brace expansion, variables not seen by R0; R0 does not guard ~/.claude/settings.json.
- V6 gaps: README/HOOKS/.env.example still say neo4j.env alone enables Neo4j; Neo4j Session lacks workspace_root; marks inherited via D21 are not derivable from stored steps.
- Recorder down ⇒ outbound commands denied in this repo (by design, D4).
- Decision path writes sessions.json with fsync on every hook (`SessionStore.save`); a latency floor and file I/O on the request path; no card owns it yet.
- R0 does not guard ~/.claude/settings.json (D24: a hook source the agent can write); V3a reports whether an allow there can beat our deny.
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2c.
- One unknown event name disables a whole hooks.json · D23, V3a.
- The agent leaves Cursor's sandbox unasked · D22, V3a check.
- Push block is a guard, not a lock (`--no-verify`, env var, `sh -c`; Cursor agents not covered) · docs/learnings.md.

## Next 3 actions
1. When a worker reports: read `head -n 6` of its report, review, merge on the owner's OK, update STATE.
2. After V3a/V5a merge: write V3b and V5b briefs (agent-ready-tickets, pass 2 only).
3. D9 review, then V2c and V8b briefs (after V6); V1b SPEC catch-up.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
