# V2c capture · one chat on Cursor 3.25.9: write, edit, parallel reads, @-attached read
Status: done 2026-10-18 · owner ran it, lead read the hook log (counts and labels only)
Result: one `tool_use_id` covers a whole edit (Read and Write); `afterFileEdit` has no id; reads pair by id even out of order
Evidence: owner's hook log, 12 events of one chat; ids shown as T0–T4, paths as F0–F3 (all absolute), no values kept
Needs the owner: nothing (afterFileEdit fallback approved 2026-10-18, D9 note)
Details: below

The owner asked the agent, with file tools only: create `scratch-capture.txt`, edit it, read
README.md and SPEC.md in one step, read one @-attached file. Recorder up, dev wiring
(`.cursor/hooks.json`, five events), every decision allow. One `generation_id` for the turn.

| # | Time (UTC) | Event | tool_name | Id | File | Action |
|---|---|---|---|---|---|---|
| 0 | 20:05:11 | preToolUse | Read | T0 | F0 | create: the tool checks the file first |
| 1 | 20:05:12 | preToolUse | Write | T0 | F0 | create |
| 2 | 20:05:12 | afterFileEdit | | none | F0 | create |
| 3 | 20:05:17 | preToolUse | Read | T1 | F0 | edit |
| 4 | 20:05:18 | beforeReadFile | | T1 | F0 | edit |
| 5 | 20:05:19 | preToolUse | Write | T1 | F0 | edit (no afterFileEdit followed) |
| 6 | 20:05:27 | preToolUse | Read | T2 | F1 | parallel read |
| 7 | 20:05:27 | preToolUse | Read | T3 | F2 | parallel read |
| 8 | 20:05:28 | beforeReadFile | | T3 | F2 | parallel read (halves return in reverse order) |
| 9 | 20:05:28 | beforeReadFile | | T2 | F1 | parallel read |
| 10 | 20:05:32 | preToolUse | Read | T4 | F3 | @-attached file, read with the normal tool |
| 11 | 20:05:32 | beforeReadFile | | T4 | F3 | `attachments` empty; no separate attachment event |

Findings
- A Read of a file that does not exist yet (row 0) fires no `beforeReadFile`.
- One tool call can fire two `preToolUse` events (Read, then Write) under one id: an edit is one action.
- `afterFileEdit` carries no `tool_use_id` (1 of 1) and fired for the create only, not for the edit.
- The hook log keeps times to the second only; ordering within a second is file order.
- Expected steps after V2c: 4 (create, edit, read F1, read F2) + 1 (read F3) = 5, not 12.
