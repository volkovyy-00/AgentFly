# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-15 22:53 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: Spikes S1 ✅ S2 ✅ (S1 app half only); S3 S4 S5 not started; no V-card started; DECISIONS partly approved.
Pending decisions: D2 D3 D5 D6 D7 D8 D9 D11 D12 D13 D15 D16 D17 D18 D19

## Spikes and cards
- S1 passed (app only) · docs/spikes/S1-global-hooks.md · global hooks fire in a fresh folder (no trust prompt); R1 deny shown; `ask` pauses shell (2/2); allow-with-message invisible (2/2); `tool_use_id` on preToolUse + beforeShellExecution only; `cursor-agent` not tested.
- S2 passed · docs/spikes/S2-tamper.md · system hooks.json fires, root-owned files resisted (a),(b),(d); deny survived user/project allow-all hooks (f),(g); findings F1, F2, (h).
- S3 not started · needs Yevhenii's 10 rule sentences · report would be docs/spikes/S3-rule-fit.md.
- S4 not started · report would be docs/spikes/S4-trail.md.
- S5 not started · after S2; reuses /tmp/af-fresh · docs/spikes/S5-brief.md.
- V1–V9 not started; BOARD.md is revision 3.

## In flight
none

## Machine state (verified 2026-10-15 22:31 CEST unless marked)
- /Library/Application Support/Cursor/hooks.json and /Library/Application Support/AgentFly/: absent (verified). Looks like s2.sh restore was already run.
- ~/.cursor/hooks.json: absent (verified). Repo .cursor/hooks.json: present (verified).
- Recorder: running, pid 34143, GET /api/steps 200 (verified); started about 22:19.
- ~/.config/flightrecorder/sessions.json: restored from backup, no `s2-forged` entries (verified); 35 sessions, 18 marked.
- /tmp/af-spike: throwaway scripts, logs and sessions.json.bak (verified, never commit). Copy in logs/spike/ (gitignored); after a reboot run `cp -Rp logs/spike/. /tmp/af-spike/`.
- /tmp/af-fresh: .env (fake demo value) and test.txt; no .cursor/ (verified).
- /usr/local/Cellar/af-s2-test: removed (verified).
- For S5, global hooks must be installed again first: `/tmp/af-spike/s1.sh real` (user-level, moves repo hooks aside) or `s2.sh install` (sudo); then `s1.sh restore` or `s2.sh restore` after.

## Waiting on Yevhenii
1. Confirm you ran `sudo -v` just before the (d) check (S2 report assumes yes).
2. Write 10 rule sentences for S3, and say whether a cloud model may draft rules (D13).
3. D11: approve warn = `ask` on shell, accept "Always Run", re-check `ask` in the mode you will demo in.
4. D5: choose an interpreter or launcher the agent cannot change (blocks V3).
5. Approve the pending decisions (line 4).
6. S1 CLI half: install `cursor-agent` and test, or accept "not tested".
7. Go-ahead for S3, S4, S5 (S5 needs hooks reinstalled, see Machine state).

## Decisions changed since last handoff (first handoff: all of these)
- D1 approved, option A (sudo default), wording fixed in its status line.
- D4 approved (KeepAlive in D8/V3; message says `agentfly start`). D10 approved with change (quoted heredoc is literal). D14, D20 approved.
- D9, D11: S1 results added. D11 recommendation revised (warn = ask on shell), still proposed.
- D3, D12, D13: UI draft form dropped; `agentfly rules draft` only.
- D19: HEAD allowed only on static/plain Starlette routes, 405 asserted; /docs, /redoc, /openapi.json switched off in V2.
- S2 result lines added to D1, D2, D3, D4, D5, D8, D19.

## Open risks and findings
- F1 quoting: unquoted path with a space made python exit 2 and Cursor denied everything · docs/spikes/S2-tamper.md
- F2 writable interpreter: /usr/bin/python3 launches an admin-writable python.org framework · S2-tamper.md, D5
- (h) offline gap: recorder down + secret read, curl allowed; sandbox escalation · S2-tamper.md, D4
- Hook messages on allow are invisible in Cursor · S1-global-hooks.md, D11
- Python 3.13 is the system interpreter here; AGENTS.md "Hook facts" still say Cursor 3.5.17 (now 3.24.12); V1 rewrites it.

## Next 3 actions
1. Yevhenii answers the Waiting list items 1–4.
2. Run S3 and S4 in parallel (S3 needs the sentences), then S5.
3. After all spikes: Yevhenii approves DECISIONS.md, then V1.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
