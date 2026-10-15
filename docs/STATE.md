# STATE (lead handoff; overwrite, never append)
Updated: 2026-10-16 00:57 CEST (Europe/Prague) · HEAD and commits since this file changed: `docs/roles/state-check.sh` (the lead hook prints it)
Phase: Spikes S1 ✅ S2 ✅ S4 ✅ (S1 app half only); S3 waits for the owner's sentences; S5 after S3; no V-card started.
Pending decisions: D2 D3 D6 D7 D8 D9 D12 D13 D16 D17 D18 D19

## Spikes and cards
- S1, S2, S4: done, one line each under BOARD.md `## Done`.
- S1 limits: app half only (`cursor-agent` not tested); `ask` pauses shell; allow messages invisible · docs/spikes/S1-global-hooks.md
- S2 limit: (d) sudo needed a password, but the grace-period claim is unproven (owner unsure `sudo -v` ran just before) → re-run in S5 · docs/spikes/S2-tamper.md
- S4: owner chose the trail; D15 approved; V8 gained half-screen (~700 px), hide/resize Why card, separate rows for repeated blocks, and a live check before the lane graph moves to a tab · docs/spikes/S4-trail.md
- S3 not started · go given; needs the owner's 10 rule sentences; cloud-model drafting OK for S3 only · report would be docs/spikes/S3-rule-fit.md.
- S5 not started · after S3; reuses /tmp/af-fresh; includes the S2 (d) sudo re-run · report would be docs/spikes/S5-brief.md.
- V1–V9 not started; BOARD.md is revision 3 (S3, S5, V8 cards edited 2026-10-16).

## In flight
none

## Machine state (verified 2026-10-16 00:55 CEST unless marked)
- /Library/Application Support/Cursor/hooks.json and /Library/Application Support/AgentFly/: absent (verified).
- ~/.cursor/hooks.json: absent (verified). Repo .cursor/hooks.json: present (verified).
- Recorder: not running, nothing listens on 8787 (verified). Start: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`.
- No worktrees besides main; nothing listens on 5173 (verified).
- ~/.config/flightrecorder/sessions.json: 35 sessions, 18 marked, no `s2-forged` entries (verified).
- /tmp/af-spike: throwaway scripts, logs and sessions.json.bak (present, verified; never commit). Copy in logs/spike/ (gitignored); after a reboot run `cp -Rp logs/spike/. /tmp/af-spike/`.
- /tmp/af-fresh: .env (fake demo value) and test.txt only; no .cursor/ (verified).
- /usr/local/Cellar/af-s2-test: absent (verified).
- For S5, global hooks must be installed again first: `/tmp/af-spike/s1.sh real` (user-level, moves repo hooks aside) or `s2.sh install` (sudo); then `s1.sh restore` or `s2.sh restore` after.

## Waiting on owner
1. Write 10 rule sentences for S3.
2. Approve the pending decisions (line 4).
3. S1 CLI half: install `cursor-agent` and test, or accept "not tested".

## Decisions changed since last handoff (aa3e7f2)
- D5 approved 2026-10-16: one stdlib-only hook file on a bundled root-owned standalone Python under /Library/Application Support/AgentFly/; doctor checks interpreter permissions; quoted path (F1). V3 picks the build and update path.
- D11 approved 2026-10-16 as revised: warn = `ask` on shell, allow + UI mark elsewhere; "Always Run" accepted; no other demo mode named.
- D15 approved 2026-10-16 after S4: option A; S4's requests and the live check are in V8; repeated blocks stay separate rows.
- D13 still proposed; S3 may use a cloud model (sentences + schema only).
- D1: S2 sudo grace-period note marked unproven. DECISIONS revision 4 note lists these.

## Open risks and findings
- F1 quoting: unquoted path with a space made python exit 2 and Cursor denied everything · docs/spikes/S2-tamper.md
- F2 writable interpreter: /usr/bin/python3 launches an admin-writable python.org framework · S2-tamper.md; fix approved in D5, built in V3
- (h) offline gap: recorder down + secret read, curl allowed; sandbox escalation · S2-tamper.md, D4
- Hook messages on allow are invisible in Cursor · S1-global-hooks.md, D11
- Python 3.13 is the system interpreter here; AGENTS.md "Hook facts" still say Cursor 3.5.17 (now 3.24.12); V1 rewrites it.

## Next 3 actions
1. The owner writes the 10 S3 sentences; the lead briefs S3 (worker-backend, own worktree).
2. S5 after S3 (reinstall global hooks first; includes the sudo re-run).
3. After all spikes: the owner approves DECISIONS.md, then V1.

Model used for rehearsals: Grok 4.7 High in Cursor chats.
