# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 15:17 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: v2b-merged. S1–S5 ✅, V1a ✅, V2 ✅ (3da6dc7), V8 ✅ (92e7fdc, 4af8125), V2b ✅ (79a46a7). Nothing in flight; next wave not yet chosen.
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1–S5, V1a, V2, V8, V2b.
- Ready now (V2 and V2b merged), no briefs yet: V3 (CLI install, bundled Python), V5 (rules file, normalisation, R0), V6 (local store, history API, Neo4j off by default), V4 (Homebrew + release; its last check needs V3).
- Lead's proposal to the owner (unanswered): V3 ∥ V5 ∥ V6 now (non-overlapping May touch), V4 optional fourth; V8b and V2c after V6 (same recorder files: step record, memory.py, store.py).
- V2c: `tool_use_id` step merge + duplicate-read proposal; brief after the lead's D9 review.
- V8b: recorder fields `rule_text`, `user_message`, `agent_message`, `highlighted`, `/health` `last_hook_at` + `offline_guard_count` (V2b already reports the count; check before briefing).
- V1b (lead): SPEC lacks D13 = C, S3/S5 facts, D21–D25, R0 `agentfly serve`, 401/403 → guard, all one-liners denied offline, V2b's 0.5 s wait and latency note; D16 still open.
- Brief writing: agent-ready-tickets, pass 2 (fresh verify) yes, oracle pass only if the owner asks. Cards V3/V5 put commands under `agentfly/cli/commands/`, but V2 put `serve` at `agentfly/cli/serve.py`; fix in the briefs.
- V3 card: re-measure hook latency with the bundled Python (V2b p95 69 ms on the dev Python vs 50 ms target; owner accepted until V3).
- V5 card: R0 also blocks `agentfly serve`, `agentfly stop`, `agentfly uninstall`, `brew services` (owner 2026-10-16).

## In flight
none

## Machine state (verified 2026-10-16 15:15 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present (`.venv/bin/python hooks/hook.py`, no arguments → acts as `cursor`).
- Recorder: NOT running (nothing on 8787; PID 90283 gone). While it is down, Cursor in this repo denies outbound commands and every `python -c`/`node -e` (offline guard); the deny says `agentfly start`, which arrives in V3. Start now: `uv run agentfly serve`.
- Files: ~/.config/agentfly (neo4j.env, token, migration marker), ~/.local/share/agentfly/sessions.json (37 sessions). ~/.config/flightrecorder gone (migrated 13:28 byte-identical). Backup: ~/.config/flightrecorder.bak-2026-10-16 (mode 700).
- AuraDB: Session 51, Step 98 (15:15). Owner said leave it, no --clear. Tests no longer touch it (live tests need AGENTFLY_TEST_NEO4J_ENV); a running recorder still writes real steps there while neo4j.env exists, until V6.
- Worktrees: main (274a50b + this handoff). Merged and removable: ag-v2-package, ag-v8-trail, ag-v2b-hook-client (not removed; owner's call).
- Git: core.hooksPath absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push`, `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`. origin/main = 274a50b (owner pushed 2026-10-16; this handoff commit is local only). origin also has branch ag-31-sunset-old-page, unexplained (ask the owner). Origin repo is PUBLIC.
- /tmp/af-spike and /tmp/af-fresh present (spike scripts, S5 test project; copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`).
- No Xcode Command Line Tools: `make` (and other /usr/bin dev shims) open an install dialog.

## Waiting on owner
1. Next wave: how many workers and which cards (lead proposes V3, V5, V6; V4 optional).
2. Branch ag-31-sunset-old-page on origin: keep or delete.

## Decisions changed since last handoff (ba74ffe)
- D21 approved option A; D22, D23, D24 approved as written (owner, 2026-10-16).
- D25 approved 2026-10-16, changed by the owner: hooks always post to 127.0.0.1:8787, no port file; `AGENTFLY_PORT` read only by `serve` and tests; a configurable port would go in root-owned config (D1).
- Owner 2026-10-16: offline guard denies every inline one-liner (SPEC §9); V2b latency accepted until V3; V8 GIF dropped; AuraDB left as is.

## Open risks and findings
- Recorder down ⇒ outbound commands denied in this repo (by design, D4); start it before working in Cursor here.
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2c proposal
- One unknown event name disables a whole hooks.json; ~/.claude/settings.json is a third hook source; allow-vs-deny across sources untested · D23, D24, V3
- The agent leaves Cursor's sandbox unasked · D22
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock (`--no-verify`, env var, `sh -c`; Cursor agents not covered) · docs/learnings.md

## Next 3 actions
1. On the owner's wave choice: write briefs (V3, V5, V6, maybe V4) with agent-ready-tickets + pass 2; create worktrees `.claude/worktrees/ag-<card>-<slug>`; give first messages.
2. D9 review, then V2c and V8b briefs (after V6).
3. V1b: SPEC catch-up (list above).

Model used for rehearsals: Grok 4.7 High in Cursor chats.
