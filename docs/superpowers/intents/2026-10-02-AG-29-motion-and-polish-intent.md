# Intent: Calm motion, a dark theme and one loud block moment on /v2/
Ticket: AG-29 | Author: Yevhenii Volkovych | Date: 2026-10-02 | Status: approved (2026-10-02)

## Problem
See AG-29. `/v2/` draws the graph on a light theme, and once the 20-step window is full
every new step shifts every row. On a projector the story "secret read, THEN curl blocked"
must read without explanation, and the block must be the one loud moment.

## Proposed outcome
A dark, high-contrast `/v2/` where the camera glides down a stable timeline, new things
fade in once, a secret read and a block get their own moments, and nothing replays on the
1-second poll. Scope and animation list: see AG-29.

## Success criteria
1. AG-29's seven acceptance criteria pass, read with the points below.
2. A box's canvas position never changes while it is drawn. The one exception is an
   *instant re-anchor*: a shared box whose anchor step left the window moves at once to the
   next step that touches it, with a short fade-in. Test: slide the window; only that box
   changes row.
3. An unchanged poll causes no animation and no camera move.
4. Only the first successful response after a page load is shown without motion, and only
   if it already holds steps. It still shows the final state (amber box, SECRET SEEN chip,
   counts), but an old blocked step in it triggers no dim and no follow-resume. Every later
   step animates, including the first steps of a new chat. Mock mode animates every step.
5. The viewer can pan up and down only, within the drawn rows (no empty space), and zoom is
   off. A pan pauses following and shows "Follow", and a pan during a slide cancels the
   slide. Clicking "Follow", or a blocked or warned step arriving, resumes with one slide of
   400 ms or less from anywhere. A session change or "New session" resumes following and
   jumps without easing.
6. Every text/background pair at rest is at least 7:1, checked by an automated token test
   beside the 16 px scan. Excluded: the 40% dim, mid-fade frames and text under the top
   fade mask. Meaning is never by colour alone (word chips stay).
7. With reduced motion every change is instant (zero durations) and a blocked step still
   shows a static red border.
8. "SECRET SEEN" appears on a secret read and stays until a session change or "New session".
9. Docs match: SPEC § 6 ("keeps the newest step in view unless the viewer has scrolled
   away; a Follow button returns"), `design.md` § 5 and `ui/README.md` (pan on, stable
   rows), and AG-31's keep-or-drop list.

## Affected users and systems
`ui/src/graph/` (layout, viewport, window, GraphView, nodes, useRecorder),
`ui/src/index.css`, `ui/src/test-setup.ts` (a `matchMedia` stub), `ui/package.json`
(`motion`), committed `ui/dist`, SPEC.md § 6, `design.md` § 5, `ui/README.md`, Jira AG-28
(comment), AG-29, AG-31. AG-30 builds on the same layout.

## Constraints
AGENTS.md checks and the stale-build check. `motion` is the only new dependency (approved;
pin its version). 16 px text floor. System fonts only (no CDN). No `dangerouslySetInnerHTML`.
Animate inner elements only. Stable node ids. No `fitView` after a session's first paint.
Each animation 800 ms or less (the 1.5 s dim hold is the one exception). Work order: camera
slide, then animations, then theme.

## Decisions
- Each step gets a stable row when first seen (never `order`), so the camera moves, not the
  boxes. Mechanism: spec.
- Dark theme only. This settles AG-31's dark-mode item.
- Look B (confirmed 2026-10-02): dark-tinted fills with bright borders (red `#7f1d1d`, blue
  `#1e3a8a`, purple `#4c1d95`, grey `#374151`) and light text. Secret files stay amber with
  dark text. The R1 rule box uses a dark red fill and keeps its pill shape. Chips use a tint
  with dark text. Muted text is lightened to about `#a8b3c5`. Reason: loudest on a
  projector, and it passes 7:1.
- React Flow's attribution link is recoloured to pass 7:1 first (assumed allowed). An
  exemption is requested only if that fails.
- Vertical pan only, zoom off. This reverses AG-28's "pan off". Reason: zoom could break
  the 16 px floor.
- No visible step number (confirmed 2026-10-02). It stays in the tooltip. Reason: it would
  cut the demo command. Tabular figures apply to counts. AG-31's step-number item is settled
  as "drop".
- The one-sentence SPEC § 6 edit is authorised (2026-10-02), which meets AGENTS.md's
  "stop and ask".
- A re-anchor and a new touch in the same poll: the brighten wins. Edges into a re-anchored
  box re-route at once and do not replay their draw-in.
- Scope wins: a blocked or warned step resumes following.
- "SECRET SEEN" lives in page state. A reload mid-session may miss it until AG-30's `flagged`.

## Out of scope
A light theme, sound, 3D, a round layout. Also zoom, widening the step box, header counters,
BLOCKED banner, legend and AG-30's summary box.

## Risks
- Huge canvas coordinates in long sessions (manual check with a long replay).
- Grey, blue and purple fills differ by hue only; add a projector check.
- AG-30 changes the same layout and needs the same stable rows.
- The block's parts may not fit in 800 ms total (see Open questions).

## Open questions
- (spec) What "xN" counts (my lean: drawn steps, ticking only up).
- (spec) Block timing (assumed: the whole sequence in 800 ms, with the dim covering the
  graph only; the spec confirms it fits). Also burst handling, fade mask vs top padding and
  top-edge controls, edge draw-in vs dashes.
- (you) Approve the Jira edits: AG-29 wording (blocked or warned, drop "or zoom", figures
  not step numbers), AG-31's list, an AG-28 comment. No Jira write happens before approval.
- (you) Did AG-28's first-paint check pass in a real session? If unsure, run it first, as
  part of the camera work.
