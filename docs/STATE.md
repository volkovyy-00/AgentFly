# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 12:58 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: s5-done. S1–S5 ✅, V1a ✅ (merged b7f7192). V2 reports done (not reviewed/merged). V8 in progress (needs owner's live check).
Pending decisions: D16 D21 D22 D23 D24

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1, S2, S3, S4, S5, V1a. S1 `cursor-agent` half: owner accepted "not tested".
- S3: FAIL 7-8 band → D10 extended; D13 = C; subagent option now proposed as D21 · docs/spikes/S3-rule-fit.md
- S5 pass (smoke test; D16 open): brief used, never named (tool calls 8,8 without; 2,3 with; additional_context 3, n=1); unknown event disables whole hooks.json; Cursor runs ~/.claude/settings.json hooks; subagents: own conversation_id + parent_tool_call_id on every event; bg subagent fires no subagentStop; read events share no id; sudo -n exit=1 (D3 stands) · docs/spikes/S5-brief.md
- V2 (report head, 12:00): done, six criteria met; 292 passed, 4 skipped; web 356; "Choices I made" for the lead to confirm. Branch ag-v2-package: 4e06401, 6181149, f742667. Not yet reviewed.
- V2b: brief ready (docs/briefs/V2b.md, names `offline_guard_count`); worktree after V2 merges.
- V8 (report head, 13:05): trail at /?view=trail, Why card, health strip; 430 web tests; real Chrome at 700 px. Not done: owner live check on 8787, 60 s GIF, home switch. Needs owner: yes to start the recorder on 8787. Branch ag-v8-trail: db79e92..ae736cd. Merges after V2.
- V8b (new card, BOARD): recorder fields `rule_text`, `user_message`, `agent_message`, `highlighted`, `/health` `last_hook_at` + `offline_guard_count`; brief after V2b.
- V1b (lead): SPEC still says D13 pending; lacks S3 additions, revision 7, S5 facts and D21–D24 once approved.

## In flight
- V2 · worker-backend · .claude/worktrees/ag-v2-package · ag-v2-package · docs/reports/V2.md · docs/briefs/V2.md
- V8 · worker-ui · .claude/worktrees/ag-v8-trail · ag-v8-trail · docs/reports/V8.md · docs/briefs/V8.md

## Machine state (verified 2026-10-16 12:56 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present.
- Recorder: nothing listens on 8787 or 5173. Start: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787` (main's layout until V2 merges).
- Worktrees: main (4549bef), ag-v2-package (f742667), ag-v8-trail (ae736cd).
- Git: core.hooksPath absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push`, `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`. origin: main only (verified).
- AuraDB: resumed; owner ran `--clear` 2026-10-16, all counts 0 (as of 11:55).
- ~/.config/flightrecorder/sessions.json: 35 sessions, 18 marked (as of 11:34).
- /tmp/af-spike: spike scripts and logs incl. s5-* (copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`). /tmp/af-fresh: S5 test project (scripts/check.sh) and fake .env.
- No Xcode Command Line Tools: `make` (and other /usr/bin dev shims) open an install dialog.

## Waiting on owner
1. V8: yes to starting the recorder on 8787 for the live check, then be at the keyboard (fake_agent R1 replay, one real Cursor chat, GIF).
2. Yes or changes on D21 (subagent mark via parent link), D22 (sandbox not a control), D23 (register only accepted events; doctor), D24 (~/.claude hooks).

## Decisions changed since last handoff (f8145f9)
- D21–D24 proposed (2026-10-16) from S5, with the owner's leanings.
- V8 UI-only with fill-later fields (owner, 2026-10-16) → card V8b.
- S5 verdict pass (owner); D16 stays open until the A/B.

## Open risks and findings
- Merging V2 must keep `.venv/bin/python hooks/hook.py` working, or Cursor blocks everything in this repo · check at V2 review
- V8 and V2 both touch ui/dist build output: merge V2 first, rebuild ui/dist on V8's branch, rerun the stale-build check
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2b proposal; S5: generation_id is per turn, file_path on both
- One unknown event name disables a whole hooks.json; ~/.claude/settings.json is a third hook source; allow-vs-deny across sources untested · D23, D24, V3
- The agent leaves Cursor's sandbox unasked · D22, docs/learnings.md
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock (`--no-verify`, env var, `sh -c`; Cursor agents not covered) · docs/learnings.md

## Next 3 actions
1. Review V2: head -n 6, "Choices I made", `git diff --stat main...ag-v2-package`, run the checks on the branch, confirm `hooks/hook.py` shim; merge; create V2b's worktree and first message.
2. V8: owner's live check (8787 free, no spike running); after V2 merges, V8 rebases/rebuilds ui/dist, then home switch on the owner's yes; merge.
3. After D21–D24 answers: amend V2b/V3/V5 cards; D9 review (subagentStart record-only, read-dedup key); V1b.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
