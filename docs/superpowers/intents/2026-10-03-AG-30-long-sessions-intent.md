# Intent: Long sessions stay light, with landmarks kept in reach
Ticket: AG-30 | Author: Yevhenii Volkovych | Date: 2026-10-03 | Status: approved (2026-10-03)

## Problem
See AG-30. In a long session the 20-step window pushes out the secret read and the old
blocks the demo story relies on, and the server keeps every step forever. Size: Architectural
(the layout work on AG-29's stable rows; the API change is additive).

## Proposed outcome
After a long run, `/v2/` still draws a small, fast window, with one summary box and up to
5 landmark steps (the secret read and the newest blocks or warnings) one pan upward.
Scope, caps and numbers: see AG-30.

## Success criteria
1. AG-30's seven acceptance criteria pass, read with the points below.
2. "In view" means: on first paint the newest step is in view; the pan range reaches the
   summary box and every flagged step; no coordinate comes from `order` (test with orders
   in the tens of thousands).
3. Without `limit` the response has the same keys and values as before, up to 500 steps
   (the cap changes `?all=1` beyond that).
4. A session where `cat README.md .env` is followed by `curl` returns the marking step's
   order in a new top-level field, present only when `limit` is sent.
5. `flagged` holds at most 5 steps in total. The marking step is kept in `flagged` once it
   leaves the window; a step that is both marking and blocked counts once.
6. For that session the marking step shows a `SECRET` chip wherever it is drawn, and SECRET
   SEEN appears, also after a mid-session reload.
7. When the window slides, the summary box and flagged steps move together, instantly, one
   row. A step that drops out and becomes flagged also moves into the group, keeping its id.
   Nothing moves on an unchanged poll, window steps keep their rows, and a group move
   replays no fade-in or edge draw-in.
8. A flagged step is a step box with chips `BLOCKED R1` / `WARN R1` / `SECRET`, hung off the
   summary box, with no file, host or rule boxes of its own.
9. Docs: HOOKS.md, `README.md` (the `/v2/` paragraph), `ui/README.md` (the 20-step and
   last-10-per-poll lines, and the mock description if the mock gains `hidden` and
   `flagged`), and SPEC § 6, which gains the window, the summary box and the sentence "an
   older flagged step names its rule in its chip instead of a box".

## Affected users and systems
`recorder/memory.py`, `recorder/app.py` (marking-step capture), `ui/src/graph/`: `snapshot.ts`,
`window.ts`, `layout.ts`, `camera.ts`, `nodes.tsx`, `tones.ts`, `useRecorder.ts`, `mock.ts`,
`App.tsx`; `ui/dist`, `HOOKS.md`, `README.md`, `ui/README.md`, `SPEC.md` § 6, AG-29's
stability test in `layout.test.ts`. The old page at `/` reads the default response.

## Constraints
AGENTS.md checks and the stale-build check. No new dependencies. 16 px text floor, 7:1
contrast for new chips (a row in `tones.ts`). Only order numbers and counts are stored. The
marking-step capture and counters run in the hook path, so they stay cheap and in memory.

## Decisions
- AG-29's "a box never moves" gets one amendment, stated here, not by editing AG-29's intent:
  the group moves instantly with the window. Reason: nothing else fits "scrolls, not
  pinned" and "no empty pan space".
- "First secret read" = the step that made R1 mark the session, not the first step with
  `sensitive` (that misses `cat README.md .env`). Reason: it matches SPEC § 5 and § 2.
- No lane boxes for flagged steps. The SPEC § 6 sentence is authorised (2026-10-03).
- The reducer in `window.ts` keeps owning stable rows; `limit=20` only changes what a poll
  returns.
- After a server restart the mark survives but memory does not: no chip (assumed).
- Memory is bounded per session (500 steps, counters, at most 5 landmarks). The number of
  sessions is not capped (assumed).

## Out of scope
Merging identical steps, a ribbon, click-to-expand, cross-session views, Neo4j, lane boxes
for flagged steps, a pinned summary.

## Risks
Group edge ids tied to the oldest step; two chips plus a rule id may truncate a command in
400 px (manual check); the group hop shows on panes taller than about 1,300 px.

## Open questions
- (spec) Group geometry; whether the summary box has an edge to the oldest step.
- (spec) `limit=0`, negative, non-number, and `all=1` with `limit`.
- (spec) A dropped lane box's edge, under the 15/5 caps.
- (spec) A marking step still inside the window takes no flagged slot: so up to 5 blocked
  or warned, or 4?
- (spec) How the 500-step replay is run (mock burst or a long scenario).
- (done) Jira edit to AG-30 and AG-31 approved 2026-10-03: "in view" reworded as in
  criterion 2, "static" and "just above the oldest drawn step" replaced by the moving group,
  chip and marking-step additions, and AG-31's "until AG-30's `flagged`" line settled.
