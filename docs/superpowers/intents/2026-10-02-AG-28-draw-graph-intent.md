# Intent: Draw the live graph on the new page (new layout, mock mode)
Ticket: AG-28 | Author: Yevhenii Volkovych | Date: 2026-10-02 | Status: approved (2026-10-02)

## Problem
See AG-28. `/v2/` is a blank scaffold, so the old page can't be retired. A first
attempt on 2026-10-01 drew a blank pane on real sessions because positions came
from step numbers (about 40,000); mock mode hid it.

## Proposed outcome
`/v2/` draws the live session as a top-to-bottom timeline with side lanes, and
the newest step is always in view. Scope and layout: see AG-28.

## Success criteria
1. AG-28's six acceptance criteria all pass.
2. Reworded stability criterion: "Appending a step does not change where boxes
   still drawn sit relative to each other. The one exception is a shared box
   whose anchor step has just left the window; it moves to the next drawn step
   that touches it." A window slide shifts every row and is a separate event.
3. Test: a file touched at the first and last drawn step. Slide the window one
   step. The file box is level with the later step, other boxes keep their
   offsets, and the old step and its edges are gone. A pure append moves nothing.
4. With no steps yet, the page shows "Waiting for agent actions…".
5. Docs match the page: SPEC § 6 (rows, "files and websites above and below",
   "last 10 steps"), `ui/README.md:19`, `HOOKS.md:229`, `README.md:119`.
6. AG-28's Jira text matches this intent (see Open questions) and AG-31 lists
   the other old-page features as "keep or drop?" items.

## Affected users and systems
`ui/` (with committed `ui/dist`), SPEC.md § 6, README.md, HOOKS.md, `ui/README.md`,
the AG-28 and AG-31 text. The API is untouched. AG-29 and AG-30 build on this.

## Constraints
Approved dependencies only (`@xyflow/react`; no motion yet). No physics or layout
library. Text at least 16px in 960x1080. No `dangerouslySetInnerHTML` (server
text stays literal). OFFLINE after one failed poll (worst case 1 s gap + 1.5 s
timeout = 2.5 s, limit 3 s), tested with fake timers. AGENTS.md checks pass.

## Decisions
- The ticket authorises the SPEC § 6 edit, so AGENTS.md's "stop and ask" is met.
- Parity = acceptance criteria plus the empty state. No zoom buttons ("Fit"
  would shrink text).
- A box is dropped when no drawn step touches it.
- The page keeps earlier steps, merges by `order`, and resets when the session id changes.
- Bursts of more than 10 steps between polls: accept the loss; don't use `?all=1`.
- "New session" is remembered in `sessionStorage` (try/catch), as on the old page.
- AG-31 decides the BLOCKED banner and legend first, and when `/` stops being the demo.
- Testability: positions and the viewport come from a pure function that takes
  explicit node sizes; React Flow nodes get explicit `width` and `height`; tests
  never rely on DOM measurement. jsdom lacks `ResizeObserver` and
  `DOMMatrixReadOnly`, so the vitest setup stubs them.
- Known cost of the off-screen anchor: an edge from a visible step can run off the
  top to a box you can't see. Accepted, because the criteria only require the
  newest step and its boxes in view. A smaller row pitch reduces how often.

## Out of scope
See AG-28. Also: header counters, secret indicator, banner reason text, legend.

## Risks
- Positions must come from list place, never `order`.
- The window jump must be easy for AG-29 to replace.

## Open questions
- (spec) Stacking rule for a blocked step's host and rule boxes. Default: rule below host.
- (spec) 20 rows at about 56 px is about 1,100 px, taller than the pane. Fix the
  row pitch, hold zoom at 1 and follow the newest step.
- (you) One Jira edit to AG-28, with approval before any write: (1) reword the
  Summary sentence "does everything the old page does"; (2) reword the stability
  criterion as in criterion 2; (3) change "left the view" to "left the 20-step window".
