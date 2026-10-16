# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 13:32 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: v2-merged. S1–S5 ✅, V1a ✅ (b7f7192), V2 ✅ (merged 3da6dc7). V8 part 1 merged 92e7fdc (home unchanged); chat check passed; waits on the home switch. V2b dispatched (worktree created, owner starts the worker).
Pending decisions: D16 D21 D22 D23 D24

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1, S2, S3, S4, S5, V1a. S1 `cursor-agent` half: owner accepted "not tested".
- S3: FAIL 7-8 band → D10 extended; D13 = C; subagent option now proposed as D21 · docs/spikes/S3-rule-fit.md
- S5 pass (smoke test; D16 open): brief used, never named (tool calls 8,8 without; 2,3 with; additional_context 3, n=1); unknown event disables whole hooks.json; Cursor runs ~/.claude/settings.json hooks; subagents: own conversation_id + parent_tool_call_id on every event; bg subagent fires no subagentStop; read events share no id; sudo -n exit=1 (D3 stands) · docs/spikes/S5-brief.md
- V2 ✅ merged 3da6dc7 (lead review: checks 292 passed/4 skipped on branch and on main after `uv sync`; shim answers allow, exit 0). Done line in BOARD.
- V2b: brief rewritten 2026-10-16 in the owner's priority order (never non-zero + guard on unreadable input + fuzz; port fixed at 8787 per D25; nested stripping; install.sh/HOOKS.md paths; then guard, agent arg). Duplicates moved to new card V2c. Pass-2 review done, fixes applied (no-arg = cursor, log keeps no command text, guard paths named, fuzz adds 5000-digit number). D25 approved.
- V8 (report head, 13:40 in worker time): part 1 merged to main 92e7fdc (owner yes 2026-10-16): trail at /?view=trail, lane graph still home; on main: 296 passed, stale-build OK. Owner viewed /?view=trail on the live recorder: "looks and works fantastic". Real Cursor chat check passed (lead verified /api/steps: .env read sensitive at step 2, `curl example.invalid` blocked at step 8). GIF dropped by the owner 2026-10-16. Left: home switch on the owner's yes; worker merges main into ag-v8-trail first.
- V2c (new card, BOARD): `tool_use_id` step merge + duplicate-read proposal; brief after V2b and D9 review.
- V8b (new card, BOARD): recorder fields `rule_text`, `user_message`, `agent_message`, `highlighted`, `/health` `last_hook_at` + `offline_guard_count`; brief after V2b.
- V1b (lead): SPEC still says D13 pending; lacks S3 additions, revision 7, S5 facts and D21–D24 once approved.

## In flight
- V2b · worker-backend · .claude/worktrees/ag-v2b-hook-client · ag-v2b-hook-client · docs/reports/V2b.md · docs/briefs/V2b.md
- V8 · worker-ui · .claude/worktrees/ag-v8-trail · ag-v8-trail · docs/reports/V8.md · docs/briefs/V8.md

## Machine state (verified 2026-10-16 13:30 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present.
- Recorder: main's `agentfly serve` on 127.0.0.1:8787, PID 72988, started by the owner 13:28; /health 200. Migration ran 13:28:03: ~/.config/agentfly (neo4j.env, token, marker) and ~/.local/share/agentfly/sessions.json (36 sessions), both byte-identical to the backup; ~/.config/flightrecorder removed.
- Backup: ~/.config/flightrecorder.bak-2026-10-16 (mode 700, identical copy, taken before the merge).
- Worktrees: main (92e7fdc), ag-v2-package (f742667, merged; removable), ag-v8-trail (808c7ee, merged part 1), ag-v2b-hook-client (a21cac9).
- Git: core.hooksPath absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push`, `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`. origin: main only (verified).
- AuraDB: owner asked the lead to run `--clear` at 13:3x after the lead's pytest wrote live-test nodes; `--counts` all 0 (verified). The standard check writes to AuraDB while ~/.config/agentfly/neo4j.env exists.
- /tmp/af-spike: spike scripts and logs incl. s5-* (copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`). /tmp/af-fresh: S5 test project (scripts/check.sh) and fake .env.
- No Xcode Command Line Tools: `make` (and other /usr/bin dev shims) open an install dialog.

## Waiting on owner
1. V8: yes or no to the home switch (trail becomes /, lane graph moves to a "Graph" tab).
2. Yes or changes on D21 (subagent mark via parent link), D22 (sandbox not a control), D23 (register only accepted events; doctor), D24 (~/.claude hooks).

## Decisions changed since last handoff (f8145f9)
- D21–D24 proposed (2026-10-16) from S5, with the owner's leanings.
- D25 approved 2026-10-16, changed by the owner: hooks always 127.0.0.1:8787, no port file; `AGENTFLY_PORT` for serve and tests only; a configurable port would go in root-owned config (D1). SPEC §3/§8 note goes to V1b.
- V2 merged 3da6dc7; V2b re-prioritised by the owner; V2c split off.
- V8 UI-only with fill-later fields (owner, 2026-10-16) → card V8b.
- S5 verdict pass (owner); D16 stays open until the A/B.

## Open risks and findings
- V8 and V2 both touch ui/dist build output: merge V2 first, rebuild ui/dist on V8's branch, rerun the stale-build check
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2b proposal; S5: generation_id is per turn, file_path on both
- One unknown event name disables a whole hooks.json; ~/.claude/settings.json is a third hook source; allow-vs-deny across sources untested · D23, D24, V3
- The agent leaves Cursor's sandbox unasked · D22, docs/learnings.md
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock (`--no-verify`, env var, `sh -c`; Cursor agents not covered) · docs/learnings.md

## Next 3 actions
1. When V2b reports: head -n 6, review, run checks on its branch, merge; then V2c brief (after D9 review).
2. V8: on the owner's yes to the home switch, worker merges main into ag-v8-trail and commits the home switch; lead reviews and merges.
3. After D21–D24 answers: amend V2b/V3/V5 cards; D9 review (subagentStart record-only, read-dedup key); V1b.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
