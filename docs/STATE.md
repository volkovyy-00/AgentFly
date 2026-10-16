# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 12:00 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: v8-dispatched. S1–S4 ✅, V1a ✅ (merged b7f7192). V2 in flight (plan mode), V8 dispatched. S5 now with the owner.
Pending decisions: D16

## Spikes and cards
- Done (one line each under BOARD `## Done`): S1, S2, S3, S4, V1a.
- S1 limits: app half only (`cursor-agent` not tested); `ask` pauses shell; allow messages invisible · docs/spikes/S1-global-hooks.md
- S3: FAIL 7-8 band → D10 extended (flag variants, path_scope, pipe_into, wget flags); D13 = C; subagent option (a) 30 min pending S5 · docs/spikes/S3-rule-fit.md
- S5 not started: brief smoke test + S2 (d) sudo re-run + passive dump hook on all events, one made-up event, one foreground and one background subagent; record generation_id on both read events (D9) and workspace_roots/parent ids for subagents (S3 §5) · BOARD S5 card.
- V2 split (2026-10-16, brief over budget): V2 = package `agentfly-recorder`, v1 paths, API whitelist, cleaner leak (hooks/hook.py stays a shim); V2b = hook client (agent arg, stripping, offline guard, duplicates, port override, wait budget, read-dedup proposal). Briefs in docs/briefs/. Verify passes: both ready; oracle pass stopped by the owner, no verdict.
- V1b (lead, after S5): SPEC still says D13 pending and lacks the S3 additions and revision 7 answers.
- V8 (2026-10-16, owner): UI-only; rule text, messages, last-hook time, guard count, `highlighted` come from new card V8b (backend, after V2b); page shows them when present. Brief verified (pass 2).
- S1 `cursor-agent` half: owner accepted "not tested" (2026-10-16).

## In flight
- V2 · worker-backend · .claude/worktrees/ag-v2-package · ag-v2-package · docs/reports/V2.md · docs/briefs/V2.md
- V8 · worker-ui · .claude/worktrees/ag-v8-trail · ag-v8-trail · docs/reports/V8.md · docs/briefs/V8.md

## Machine state (verified 2026-10-16 11:34 CEST)
- /Library/Application Support/Cursor/hooks.json, /Library/Application Support/AgentFly/, ~/.cursor/hooks.json: absent. Repo .cursor/hooks.json: present.
- Recorder: nothing listens on 8787 or 5173. Start: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`.
- Worktrees: main, .claude/worktrees/ag-v2-package (5aff9e1), .claude/worktrees/ag-v8-trail (this commit).
- Git: core.hooksPath is absolute (main's docs/roles/git-hooks: pre-commit, pre-push). `.claude/settings.json` denies `git push` and `git -C * push *`. Owner pushes with `AGENTFLY_ALLOW_PUSH=1`.
- origin still has ag-s3-rule-fit and ag-v1a-spec (pushed by workers, unasked).
- ~/.config/flightrecorder/sessions.json: 35 sessions, 18 marked.
- AuraDB: resumed, reachable 11:50 (counts OK). `--clear` blocked by the auto-mode classifier; owner runs it.
- /tmp/af-spike: throwaway scripts and logs (copy in logs/spike/, gitignored; after a reboot `cp -Rp logs/spike/. /tmp/af-spike/`). /tmp/af-fresh: .env (fake) and test.txt only.
- For S5, reinstall global hooks first: `/tmp/af-spike/s1.sh real` (user-level) or `s2.sh install` (sudo); `s1.sh restore` / `s2.sh restore` after.

## Waiting on owner
1. Run `! uv run python -m recorder.store --clear` (test data; lead's run was blocked by the classifier).
2. Delete pushed branches: `! AGENTFLY_ALLOW_PUSH=1 git push origin --delete ag-v1a-spec ag-s3-rule-fit`.
3. Be at the keyboard for S5 (Cursor app, sudo).
4. Start the V8 worker (first message from the lead).

## Decisions changed since last handoff (bb72b37)
- Revision 5: D2 D3 D6 D7 D8 D9 D12 D17 D18 D19 approved as recommended; D19 turns /docs off; D3 reopens if the S5 sudo re-run fails.
- D6: PyPI name `agentfly-recorder`, hatchling; PyPI `agentfly` 0.7.2 also installs an `agentfly` command (known conflict).
- Revision 6: D10 extended after S3; D13 approved as C (no plain language in v1).
- Revision 7: D10 heredoc exception excludes shells/interpreters (sh bash zsh python* node ruby perl, also via env/sudo/xargs); D5 missing client = loud failure; D14 `highlighted` verdict; D9 read-dedup key proposed by V2b, revisit event list after S5.
- SPEC §3/§7 (lead, 5aff9e1): the recorder's first start migrates ~/.config/flightrecorder.

## Open risks and findings
- Cleaner leak (today's code): attached short-option values (`-uuser:X`, `-pX`, `-p'X'`, `-H'Authorization: …'`) stored as is, in memory and Neo4j · fixed by V2
- Merging V2 must keep `.venv/bin/python hooks/hook.py` working, or Cursor blocks everything in this repo · V2 criterion
- File reads fire preToolUse and beforeReadFile with no shared id → recorded twice · V2b proposal, S5 data
- Subagents may get a new conversation_id with no parent link (untested report) · S5
- F1 quoting and F2 writable interpreter · docs/spikes/S2-tamper.md; fixes in D5, built in V3
- Push block is a guard, not a lock: `--no-verify`, the env var, and `sh -c` get through; Cursor agents are not covered by the deny rule · docs/learnings.md

## Next 3 actions
1. When the owner relays V2's plan or report: review (head -n 6, `git diff --stat main...ag-v2-package`, checks), merge, then create V2b's worktree.
2. S5 with the owner; then D16, D9 revisit, V1b.
3. When V8 reports its plan: check the Why card hide/resize proposal reaches the owner; write V8b's brief after V2b.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
