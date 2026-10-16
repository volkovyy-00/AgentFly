# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 14:50 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: v2b-merged. S1–S5 ✅, V1a ✅, V2 ✅ (3da6dc7), V8 ✅ (4af8125), V2b ✅ (79a46a7). Nothing in flight; next wave to be briefed.
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1, S2, S3, S4, S5, V1a. S1 `cursor-agent` half: owner accepted "not tested".
- S3: FAIL 7-8 band → D10 extended; D13 = C; subagent option now proposed as D21 · docs/spikes/S3-rule-fit.md
- S5 pass (smoke test; D16 open): brief used, never named (tool calls 8,8 without; 2,3 with; additional_context 3, n=1); unknown event disables whole hooks.json; Cursor runs ~/.claude/settings.json hooks; subagents: own conversation_id + parent_tool_call_id on every event; bg subagent fires no subagentStop; read events share no id; sudo -n exit=1 (D3 stands) · docs/spikes/S5-brief.md
- V2 ✅ merged 3da6dc7 (lead review: checks 292 passed/4 skipped on branch and on main after `uv sync`; shim answers allow, exit 0). Done line in BOARD.
- V2b ✅ merged 79a46a7 (lead check on b73b7d4 and on main: 650 passed / 4 skipped; shim on main answers, exit 0). AGENTS.md updated for V2b in the same lead commit.
- V8 ✅ merged 4af8125 (trail is /, lane graph /?view=graph). Done line in BOARD. Stale README/HOOKS lines go to V2b addendum (6).
- V2c (new card, BOARD): `tool_use_id` step merge + duplicate-read proposal; brief after V2b and D9 review.
- V8b (new card, BOARD): recorder fields `rule_text`, `user_message`, `agent_message`, `highlighted`, `/health` `last_hook_at` + `offline_guard_count`; brief after V2b.
- V1b (lead): SPEC still says D13 pending; lacks S3 additions, revision 7, S5 facts and D21–D24 once approved.

## In flight
none

## Machine state (verified 2026-10-16 13:30 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present.
- Recorder: main's `agentfly serve` on 127.0.0.1:8787, PID 90283, detached, restarted by the V8 worker with the owner's yes at 13:50 (in-memory steps from before are gone); token written 13:50:50. Migration ran 13:28:03: ~/.config/agentfly (neo4j.env, token, marker) and ~/.local/share/agentfly/sessions.json (36 sessions), both byte-identical to the backup; ~/.config/flightrecorder removed.
- Backup: ~/.config/flightrecorder.bak-2026-10-16 (mode 700, identical copy, taken before the merge).
- Worktrees: main; merged and removable: ag-v2-package, ag-v8-trail, ag-v2b-hook-client.
- Git: core.hooksPath absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push`, `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`. origin: main only (verified).
- AuraDB: cleared at 13:3x; as of 14:06 counts Session 51, Step 98 (live recorder writes plus the V8 worker's live tests). The standard pytest runs the 4 live Neo4j tests while ~/.config/agentfly/neo4j.env exists; the lead runs `-k 'not live'`.
- /tmp/af-spike: spike scripts and logs incl. s5-* (copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`). /tmp/af-fresh: S5 test project (scripts/check.sh) and fake .env.
- No Xcode Command Line Tools: `make` (and other /usr/bin dev shims) open an install dialog.

## Waiting on owner
none (owner waits for the V2b worker's addendum report)

## Decisions changed since last handoff (f8145f9)
- D21 approved option A; D22, D23, D24 approved as written (owner, 2026-10-16).
- Owner 2026-10-16: offline guard denies every one-liner (SPEC §9); V2b p95 122 ms accepted until V3; AuraDB left as is (no --clear).
- D21–D24 proposed (2026-10-16) from S5, with the owner's leanings.
- D25 approved 2026-10-16, changed by the owner: hooks always 127.0.0.1:8787, no port file; `AGENTFLY_PORT` for serve and tests only; a configurable port would go in root-owned config (D1). SPEC §3/§8 note goes to V1b.
- V2 merged 3da6dc7; V2b re-prioritised by the owner; V2c split off.
- V8 UI-only with fill-later fields (owner, 2026-10-16) → card V8b.
- S5 verdict pass (owner); D16 stays open until the A/B.

## Open risks and findings
- Fixed in V2b: second `serve` no longer rotates the token; 401/403 → guard. R0 adding `agentfly serve` is V5's.
- With the recorder down, Cursor in this repo now denies outbound commands; the deny names `agentfly start`, which arrives in V3 (until then `uv run agentfly serve`).
- The live recorder writes real steps to AuraDB while neo4j.env exists; V6 makes Neo4j off by default.
- V8 and V2 both touch ui/dist build output: merge V2 first, rebuild ui/dist on V8's branch, rerun the stale-build check
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2b proposal; S5: generation_id is per turn, file_path on both
- One unknown event name disables a whole hooks.json; ~/.claude/settings.json is a third hook source; allow-vs-deny across sources untested · D23, D24, V3
- The agent leaves Cursor's sandbox unasked · D22, docs/learnings.md
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock (`--no-verify`, env var, `sh -c`; Cursor agents not covered) · docs/learnings.md

## Next 3 actions
1. Owner picks the next wave (lead proposal: V3 ∥ V5 ∥ V6 now; V4 small, any time; V8b and V2c after V6, same recorder files). Lead writes their briefs (agent-ready-tickets) and creates worktrees.
2. D9 review before the V2c brief (subagentStart record-only, read-dedup key).
3. V1b (lead): SPEC for D21–D25, R0 `agentfly serve`, 401/403 guard, one-liners, latency; D16 still open.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
