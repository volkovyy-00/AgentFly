# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 12:50 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: s5-done. S1–S5 ✅, V1a ✅ (merged b7f7192). V2 in flight (plan mode), V8 dispatched. S5 ✅ pass (smoke test; D16 open).
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1, S2, S3, S4, S5, V1a.
- S1 limits: app half only (`cursor-agent` not tested); `ask` pauses shell; allow messages invisible · docs/spikes/S1-global-hooks.md
- S3: FAIL 7-8 band → D10 extended (flag variants, path_scope, pipe_into, wget flags); D13 = C; subagent option (a) 30 min pending S5 · docs/spikes/S3-rule-fit.md
- S5 done: brief used not mentioned (8,8 vs 2,3 tool calls; additional_context 3, n=1); unknown event disables whole hooks.json; Cursor runs ~/.claude/settings.json hooks; subagents: own conversation_id + parent_tool_call_id on every event, bg subagent no subagentStop; read dedup: no shared id; sudo -n exit=1 (D3 stands) · docs/spikes/S5-brief.md
- V2 split (2026-10-16, brief over budget): V2 = package `agentfly-recorder`, v1 paths, API whitelist, cleaner leak (hooks/hook.py stays a shim); V2b = hook client (agent arg, stripping, offline guard, duplicates, port override, wait budget, read-dedup proposal). Briefs in docs/briefs/. Verify passes: both ready; oracle pass stopped by the owner, no verdict.
- V1b (lead, after S5): SPEC still says D13 pending and lacks the S3 additions and revision 7 answers.
- V8 (2026-10-16, owner): UI-only; rule text, messages, last-hook time, guard count, `highlighted` come from new card V8b (backend, after V2b); page shows them when present. Brief verified (pass 2).
- S1 `cursor-agent` half: owner accepted "not tested" (2026-10-16).

## In flight
- V2 · worker-backend · .claude/worktrees/ag-v2-package · ag-v2-package · docs/reports/V2.md · docs/briefs/V2.md
- V8 · worker-ui · .claude/worktrees/ag-v8-trail · ag-v8-trail · docs/reports/V8.md · docs/briefs/V8.md

## Machine state (verified 2026-10-16 11:34 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/: absent. ~/.cursor/hooks.json: absent (S5 restored 12:40, verified); remove with `/tmp/af-spike/s5.sh restore`. Repo .cursor/hooks.json: present.
- Recorder: nothing listens on 8787 or 5173. Start: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`.
- Worktrees: main, .claude/worktrees/ag-v2-package (5aff9e1), .claude/worktrees/ag-v8-trail (this commit).
- Git: core.hooksPath is absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push` and `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`.
- origin: main only (owner deleted ag-s3-rule-fit, ag-v1a-spec 2026-10-16; verified).
- ~/.config/flightrecorder/sessions.json: 35 sessions, 18 marked.
- AuraDB: resumed; owner ran `--clear` 2026-10-16, all counts 0 (verified).
- /tmp/af-spike: throwaway scripts and logs (copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`). /tmp/af-fresh: .env (fake) and test.txt only.
- S5 scripts/logs: /tmp/af-spike/s5-* (copy in logs/spike/). /tmp/af-fresh now holds the S5 test project.

## Waiting on owner
1. Start the V8 worker (first message from the lead).

## Decisions changed since last handoff (bb72b37)
- Revision 5: D2 D3 D6 D7 D8 D9 D12 D17 D18 D19 approved as recommended; D19 turns /docs off; D3 reopens if the S5 sudo re-run fails.
- D6: PyPI name `agentfly-recorder`, hatchling; PyPI `agentfly` 0.7.2 also installs an `agentfly` command (known conflict).
- Revision 6: D10 extended after S3; D13 approved as C (no plain language in v1).
- Revision 7: D10 heredoc exception excludes shells/interpreters (sh bash zsh python* node ruby perl, also via env/sudo/xargs); D5 missing client = loud failure; D14 `highlighted` verdict; D9 read-dedup key proposed by V2b, revisit event list after S5.
- SPEC §3/§7 (lead, 5aff9e1): the recorder's first start migrates ~/.config/flightrecorder.

## Open risks and findings
- Cleaner leak (today's code): attached short-option values (`-uuser:X`, `-pX`, `-p'X'`, `-H'Authorization: …'`) stored as is, in memory and Neo4j · fixed by V2
- Merging V2 must keep `.venv/bin/python hooks/hook.py` working, or Cursor blocks everything in this repo · V2 criterion
- File reads fire preToolUse and beforeReadFile with no shared id (confirmed S5) → recorded twice · V2b proposal
- Subagents: new conversation_id, linked by parent_tool_call_id (S5) → S3 option (c) viable; V5/V1b to use it
- One unknown event name disables a whole hooks.json; Cursor also runs ~/.claude/settings.json hooks (S5) · V3 doctor, V1b SPEC §8/§10
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock: `--no-verify`, the env var, and `sh -c` get through; Cursor agents are not covered by the deny rule · docs/learnings.md

## Next 3 actions
1. When the owner relays V2's plan or report: review (head -n 6, `git diff --stat main...ag-v2-package`, checks), merge, then create V2b's worktree.
2. Owner's S5 follow-ups: propose subagent taint via parent link, sandbox-not-a-control, doctor event check, ~/.claude hook source; then D9 review, V1b.
3. When V8 reports its plan: check the Why card hide/resize proposal reaches the owner; write V8b's brief after V2b.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
