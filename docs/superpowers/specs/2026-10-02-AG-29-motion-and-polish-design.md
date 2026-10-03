# AG-29 design: calm motion, dark theme, one loud block moment on `/v2/`

Ticket: AG-29 | Intent: `docs/superpowers/intents/2026-10-02-AG-29-motion-and-polish-intent.md` (approved 2026-10-02) | Path: architectural | Status: draft, awaiting review

This spec does not repeat the intent. It resolves the intent's `(spec)` questions and fixes the design the plan will follow. Intent decisions are not reopened. "`design.md` § 5" in the intent means § 5 (Viewport) of `docs/superpowers/specs/2026-10-02-AG-28-draw-graph-design.md`; there is no `design.md` file.

## 1. What is built

`/v2/` becomes a dark, high-contrast page. The camera glides down a timeline whose boxes never move. New things fade in once. A secret read and a block get their own moments. An unchanged poll does nothing. The API and the recorder are not changed.

Files: `ui/src/graph/` (`window.ts`, `layout.ts`, `viewport.ts`, `GraphView.tsx`, `nodes.tsx`, `useRecorder.ts`, `mock.ts`, `types.ts`; new `camera.ts`, `choreography.ts`, `tones.ts`, `WipeEdge.tsx`, `motionPolicy.ts`), `ui/src/App.tsx`, `ui/src/index.css`, `ui/src/test-setup.ts`, `ui/package.json` (`motion`, pinned exactly), committed `ui/dist`.

## 2. Resolved `(spec)` questions

| Question | Resolution |
|---|---|
| What `xN` counts | The drawn steps that touch the box, derived in layout so it always matches the visible edges. The number ticks only when it rises; it drops silently when an old step leaves. Shown on file, host and rule boxes when 2 or more. The ticket names files only; hosts and rules are an addition (a rule at x2 means blocked twice). |
| Block timing | The whole sequence fits in 800 ms (section 6). The 1.5 s dim hold is the one exception. The dim covers the graph only. |
| Burst handling | Camera: one slide per poll, however many steps arrived. Animations: staggered, the last step starts by 350 ms (section 6). |
| Fade mask vs top padding and top-edge controls | `TOP_PAD` = 96 px = the mask height. Controls live in that 96 px band, above the mask (section 5). |
| Edge draw-in vs dashes | An SVG mask wipe, not `pathLength` or `dashoffset` (which break dashes) and not `clip-path` (a horizontal edge has a zero-height box). Section 6. |
| Where is `design.md` § 5 | The AG-28 spec § 5. Updated in section 10. |

## 3. State: stable rows (`window.ts`, pure)

- Each step gets a `row` when first seen, from a per-session counter. Canvas y is `row x ROW_PITCH` for as long as the step is drawn. `order` never decides a position.
- Incoming steps are sorted by `order` before rows are assigned. Rules per incoming step:
  - a known `order` updates its fields and keeps its row;
  - an `order` above the newest held step is appended with the next row;
  - an unknown `order` below the newest held step is ignored (a live recorder cannot produce one; moving a box would break "a box's position never changes");
  - numbering that goes backwards (newest incoming below newest held) resets the window like a session change: rows restart at 0 and the camera jumps.
- The drawn set is the last 20 rows. Rows grow without bound; 10,000 steps is about 560k px, well inside double precision. A long replay is a manual check.
- Each appended step also carries `quiet`, `slot` and `of` (its index within, and the size of, the batch its poll appended), and `Step`/the placed-step type in `types.ts` gains these fields. `quiet` is true only for steps from the first successful response of a page load, and only if that response held steps. Known steps keep these values.
- **Where "first response" lives.** The reducer returns early for an empty snapshot (`window.ts`), so a flag held inside it would never flip. `useRecorder` owns it: the `snapshot` action carries `first: boolean`, true for exactly the first successful response of a page load. In mock mode it is false, unless `?mock=1&first=1` asks for the first mock tick of a page load to count as the first response (so a still first paint, including a quiet blocked step with `&burst=10`, can be checked without the server). The reducer sets `quiet` on appended steps only when `first` is true, which keeps it pure.
- **`epoch`.** The reducer state carries a counter that increments on a session change, "New session" and a backwards-numbering reset. `GraphView` receives it as a prop; this is how the camera knows to jump (it otherwise sees only `steps`).
- The reducer state also carries `secretSeen`: sticky, set when a step has `sensitive`, cleared on a session change or "New session". It is an approximation (section 12).
- An unchanged poll returns the same state object (`sameStep` compares the new fields too). A test covers it.
- Lane boxes (`layout.ts`): a box anchors at its first drawn toucher and re-anchors instantly to the next toucher when the anchor leaves the window (intent criterion 2). Each box also exposes `count` (drawn touchers) and `lastTouchRow` (the newest drawn toucher's row).
- Id helpers (`stepId`, `fileId`, `hostId`, `ruleId`, `hostEdgeId`, `ruleEdgeId`, and the others) are exported from `layout.ts` and used by both layout and the dim set. No other file builds an id by string.

## 4. Camera (`camera.ts` pure, `GraphView.tsx`)

**Test seam.** The camera logic lives in a pure `camera.ts`: target, extent, clamp, and the follow decision. `GraphView` only calls React Flow and spies on `setViewport` in tests, because jsdom cannot observe d3 transitions. `viewport.ts` keeps the zoom and pane helpers it has today.

- **The viewport is uncontrolled.** AG-28's "viewport fully controlled" invariant is retired. `GraphView` passes `defaultViewport` from the first layout (read once, at mount) and then uses imperative `setViewport` only: no `viewport` prop, no no-op `onViewportChange`. A controlled prop would snap the camera back on every frame of the transition. The AG-28 camera tests (`GraphView.test.tsx`, `viewport.test.ts`, `follow.test.ts`) are rewritten for absolute rows.
- **Zoom is locked.** `zoom = clamp(width / CONTENT_W, 0.5, 1)`, `minZoom` equal to `maxZoom`, and `zoomOnScroll`, `zoomOnPinch` and `zoomOnDoubleClick` all off.
- **Slides must not zoom.** React Flow's default `setViewport` interpolates with d3's `interpolateZoom`, which dips the zoom mid-flight even when both ends match (a 10-step burst dips to about 0.89, a long "Follow" resume to about 0.70, so 16 px text would shrink to about 11 px). Every slide passes `{ duration: ms(400), ease: easeOutCubic, interpolate: 'linear' }`. A test asserts the exact options passed to `setViewport`; a test of the props alone cannot catch this.
- **Target y.** The newest row's bottom sits `BOTTOM_PAD` above the pane bottom, but never so low that the first drawn row passes `TOP_PAD`. `BOTTOM_PAD` stays at least as tall as React Flow's attribution link: the recoloured link only passes 7:1 over the canvas, and that holds only while no box sits under it.
- **Jumps (no duration):** the first paint, a change of `epoch` (session change, "New session", backwards-numbering reset) and a pane resize of a following viewer. A resize of a paused viewer is clamped in place, not moved to the follow target.
- **Slides:** a poll that adds steps does one slide, however many steps arrived. An unchanged poll does nothing.
- **Pan:** `panOnDrag`, plus `panOnScroll` in vertical mode. The range is `translateExtent` in flow units:
  - **y:** the drawn rows, `[firstDrawnRow x ROW_PITCH - TOP_PAD / zoom, (newestRow + 1) x ROW_PITCH + BOTTOM_PAD / zoom]`. The pads are screen pixels, so they are divided by zoom (at the 644 px check, zoom is about 0.69). The extent is padded to at least the pane height, because d3 centres content that is shorter than the pane. "No empty space" means none beyond the pads.
  - **x:** `[0, pane width / zoom]`, so a pane that is a few pixels wider than the content never jumps sideways on the first drag.
- **Clamping is ours.** Neither `setViewport` nor `setTranslateExtent` re-clamps an existing viewport. `camera.ts` computes the clamped viewport. When the window slides while the viewer is paused, or the pane resizes, and the current y falls outside the new extent, `GraphView` applies the clamped viewport with no duration. Boxes never move.
- **Detecting a user pan.** d3 interrupts a running slide and emits `start` on mousedown, before any movement, so `onMoveStart` with a non-null event also fires on a plain click. A click on the page (for example, to focus the window) must not pause following. `following` becomes false on `onMove` with a non-null event, which fires only once the pointer moves; programmatic moves report a null event. If a click interrupted a slide and no movement followed, `GraphView` re-issues the slide to the current target.
- **Following resumes** on a "Follow" click, or when a non-quiet blocked or warned step arrives, with one slide of 400 ms or less from anywhere. Panning back to the newest row by hand does not resume it (the ticket's rule). A session change or "New session" resumes following and jumps. A pan or wheel gesture interrupts a running slide (d3-zoom, confirmed in its source); the browser check in section 11 still confirms it.
- `onlyRenderVisibleElements` stays off, so panning never remounts boxes and entries never replay. A test asserts the prop is not set.

## 5. Top band and the fade mask

- The pane has a 96 px top band. "New session", the SECRET SEEN chip and the Follow pill sit in it, above the mask in z-order. The OFFLINE banner drops in over it.
- The mask is a `mask-image` gradient on the React Flow container only (transparent at the top, opaque by 96 px), so the controls stay solid and a young session's first row, which starts at `TOP_PAD`, is not faded. Older boxes leave through the mask as the camera slides.
- Cost: about 17 of the 20 rows are visible at 960x1080, instead of AG-28's 18.

## 6. Choreography (`choreography.ts`, `nodes.tsx`, `WipeEdge.tsx`)

**Principle.** An animation plays when a stable-id element mounts, or when one named prop changes. An unchanged poll mounts nothing and changes nothing. Entry props are read once, at mount. Only inner elements animate; the React Flow node wrapper (which carries the position transform) is never animated.

**Timing table.** `choreography.ts` is a pure table: a start and an end per element, plus `stagger(slot, of)` = `slot x min(80, 350 / (of - 1))` ms, which is 0 when `of <= 1`. All times are relative to the step's own start, which is the poll's arrival plus the stagger. Tests assert every end is at most 800 ms (the dim hold excepted) and the last start in a burst is at most 350 ms.

| Element | Start-end (ms) |
|---|---|
| Step box fades in and rises 8 px | 0-200 |
| Chain edge wipes in | 150-350 |
| File or host edge wipes in; a new lane box fades in | 250-450 |
| Secret read: file box fills amber, one ring pulse; SECRET SEEN chip pops in | 300-800 |
| Block: dim in | 0-150 |
| Block: red border wipes in (an inner overlay, left to right) | 100-350 |
| Block: dashed edges to host and rule wipe in | 250-550 |
| Block: rule box springs in (scale 0.6 to 1, `duration: 0.35`, `bounce: 0.3`) | 450-800 |
| Block: dim hold (1500), then restore | 150-1650, restore 1650-1950 |

- **Dim is per element.** A `useDim` context at `GraphView` level holds the hot ids. Every inner element of a non-hot node or edge sets `data-dim`, and CSS applies `opacity: .4` with a transition. Hot ids are derived from the blocked step: its own box, its host box, its rule box, and its host and rule edges, all built with the id helpers (section 3). A blocked step may have a rule and no host (an R0 block), so a null host or rule is skipped. Tests assert the blocked step's own box and edges are in the hot set, with a host and without one. The band, chips, Follow pill and banner are never dimmed. The timer starts at the blocked step's own start. A second block restarts the hold, so dims do not stack.
- **Warned step:** a purple border wipe, a purple edge and the rule's spring-in, with no dim.
- **`xN` and reuse.** A lane box brightens for 300 ms when `lastTouchRow` advances, so a reuse in a full window (a drop plus an add, with the count level) still brightens. The number ticks only when `count` rises. A re-anchor and a new touch in the same poll: the brighten wins. A second block on an already-mounted rule box does not spring it in again; it brightens and ticks to `x2`. This is intended.
- **Re-anchor:** the box jumps at once (layout moves it) and its inner element fades in over 200 ms. Its edges re-route without replaying their draw-in, because they keep their ids.
- **Edge wipe.** `WipeEdge` wraps `BaseEdge` and applies an SVG mask on its first run only: a rect with `maskUnits="userSpaceOnUse"` and an explicit region that also covers the arrowhead (so a horizontal edge keeps its height), animated along the edge's dominant axis. The rect animates `width` and `height`, not `x` and `y`, which `motion` treats as CSS transforms on SVG. `WipeEdge` picks the straight or bezier path itself, because chain edges are `'straight'` and the rest are bezier. `edgeTypes` is a module-level constant, or every poll would replay every wipe. Whether a wipe has played is not recorded in an effect, which StrictMode would run twice. Each mask id is unique and the mask is removed when the wipe ends. (A CSS `inset()` clip-path fails on a zero-height box, and an SVG `<clipPath>` would work; a mask is chosen because it also reveals the arrowhead along the same region.) Anything with a delay (edges, the rule box) is hidden in its first render (`initial={{ opacity: 0 }}`) so nothing flashes before its wipe. Edge data carries `quiet`; quiet edges get no mask.
- **First paint (`quiet`).** The first response's steps show no motion. They still show the amber box, SECRET SEEN, the counts and a static red border. A blocked step in that response triggers no dim and no follow-resume.
- **Reduced motion (`motionPolicy.ts`).** One helper, `ms(n)`, returns 0 when the user prefers reduced motion. It feeds every motion transition, the stagger and the camera's `duration`. Transform and opacity animations are never left to `MotionConfig reducedMotion`, which keeps opacity animations. CSS transitions are off under `@media (prefers-reduced-motion: reduce)`. The red border stays static and always visible. The dim still applies, instantly, and restores instantly after 1.5 s: it is an opacity change, not movement.
- **OFFLINE banner:** drops in from above over 300 ms; instant when reduced.

## 7. Theme

- Tokens in `index.css` (`@theme`): canvas `#0E1116`, surface `#161B22`, ink `#E6EDF3`, muted `#a8b3c5` (canvas and surface only; on the tinted fills it measures about 4.7 to 5.2).
- Fills (Look B): grey `#374151`, blue `#1e3a8a`, red `#7f1d1d`, purple `#4c1d95`, each with a bright border of the same hue (the plan picks the tones). Secret files: amber `#f59e0b` with `#0E1116` text (the intent's `#d97706` with dark text measures about 5.6 to 5.9, which fails 7:1). The R1 rule box has a dark red fill and keeps its pill shape. Chips use a tint with dark text, and every word chip stays (BLOCKED, WARN, SECRET, SECRET SEEN).
- `EDGE_COLOR` literals are updated and stay in sync with `index.css`.
- System sans for labels, system mono for commands, `tabular-nums` on counts. No step number is drawn; it stays in the tooltip.
- The attribution link gets a transparent background and muted text. It stays exempt from the 16 px scan by name, but it is in the contrast table.
- **`xN` width.** `SECRET` and `xN` are `shrink-0` in a 220 px file box and the path is the flexible part, truncated on the left as today. `.env` and `README.md` stay untruncated with `xN` present. Lane widths do not change. Manual check.

## 8. Tests (vitest, jsdom)

- **`tones.ts` is the source of every colour pair.** It maps each variant to `{ bg, text, border, classes }`. Components render only `TONES[variant].classes`, so there is no pairing to guess from class strings. The test iterates the table: text/background at least 7:1 (excluding the 40% dim, mid-fade frames and text under the mask); border against canvas at least 3:1; `EDGE_COLOR` against canvas at least 3:1 (an addition to the intent, which asks for 7:1 on text only); every hex equals its `index.css` token; every class names an existing token. A scan asserts components contain no colour utility classes outside `tones.ts`. The existing 16 px scan is kept.
- **Reducer:** stable rows; sorting before assignment; an unknown lower `order` ignored; backwards numbering resets and bumps `epoch`; `quiet` is set only when the action carries `first: true`; `useRecorder` sends `first` for the first successful response only (an empty first response still counts, and mock sends it only with `first=1`, for its first tick); `secretSeen` sticky and cleared; an unchanged poll returns the same object.
- **Layout:** absolute rows; a window slide changes only the re-anchored box's row; `count`, `lastTouchRow`; id helpers.
- **`camera.ts` (pure):**
  - target y and the extent, with pads divided by zoom (checked at zoom 0.69);
  - x range equal to the pane width over zoom;
  - clamp of an out-of-range y;
  - the follow decision (a slide for a poll that adds steps, none for an unchanged poll, a jump on an `epoch` change, no resume for a quiet blocked step, resume for a non-quiet blocked or warned step);
  - no NaN with a 0x0 pane.
- **Camera in `GraphView` (spy on `setViewport`):**
  - every slide passes exactly `{ duration: 400 or less, ease, interpolate: 'linear' }`, and `duration: 0` when reduced;
  - a jump on a session change, "New session" and a resize;
  - a mousedown with no movement does not set `following = false` and re-issues the slide, while a move with a non-null event does;
  - the SECRET SEEN chip appears on a secret read and stays until a session change.
- **`choreography.ts`:** every end at most 800 ms (dim hold excepted); the last burst start at most 350 ms; `of = 1` is safe; reduced gives 0.
- **`GraphView`:** uncontrolled; the zoom flags; `onlyRenderVisibleElements` not set; "Follow" shows only for a user pan (non-null event); a blocked or warned step resumes following; a pan-back to the bottom does not; hot set contains the blocked step's own box and edges; dim and restore timing; reduced motion gives zero durations, including `setViewport`. `test-setup.ts` gets a `matchMedia` stub.
- **Mock:** the longer mock (about 34 steps, orders from 40,000, repeated README reads, a secret read, a blocked `curl`, a warned step) and `?mock=1&burst=N`. Existing tests and fixtures that assume the 5-step mock are updated with it. `burst` is ignored in real mode (a test asserts it).

## 9. Plan phases, build and dependency

The plan has three phases, in the ticket's order: camera slide, then animations, then theme. Each phase ends with the Check command, the web check and a rebuilt `ui/dist` passing the stale-build check, before the next starts. The first task of phase 1 is AG-28's first-paint check on a real session (`fake_agent.py` against `/v2/`), recorded before any camera work.

`motion` is the only new dependency (approved). Pin it exactly in `package.json` and the lockfile; the plan reads the version from `npm view motion version` (it reported 14.0.0 on 2026-10-02). System fonts only.

## 10. Docs and Jira

Docs. The SPEC § 6 sentence, the AG-28 spec § 5 edit and the pan and stable-row lines in `ui/README.md` land at the end of phase 1 (camera). The AG-28 spec § 4 light-theme line and the mock lines in `ui/README.md` land at the end of phase 3:
- `SPEC.md` § 6: the one authorised sentence, "keeps the newest step in view unless the viewer has scrolled away; a Follow button returns".
- AG-28 spec § 5 (replace "pan off", the controlled-viewport sentence and "to be eased by AG-29" with stable rows and pan on) and the light-theme line in § 4.
- `ui/README.md`: pan on, stable rows, the mock's longer script and `burst`.

Jira. **No write happens before you approve the text below.**
- **AG-29:** "a manual pan or zoom" becomes "a manual pan"; "tabular step numbers" becomes "tabular figures on counts"; the camera sentence says a blocked or warned step resumes following; add that `xN` also appears on host and rule boxes; add "dark theme only; settles AG-31's dark-mode item".
- **AG-31:** "Dark mode": settled, dark only (AG-29). "Step order number shown in each step box": drop (stays in the tooltip). "Glow and pulse on a blocked step": AG-29 draws a one-off border wipe and dim; a continuous glow is still AG-31's to decide.
- **AG-28 comment:** AG-29 reverses "pan off" (vertical pan on, zoom off), retires the controlled-viewport invariant and replaces "jump to be eased by AG-29" with stable rows and an imperative camera.

## 11. Manual checks (required)

- Arrowheads reveal with the mask wipe.
- A plain click on the page does not pause following. A pan during a slide interrupts it. A paused viewer is clamped when the window slides or the pane resizes. A drag on a pane a few pixels wider than the content does not shift it sideways.
- During a 10-step burst and a long "Follow" resume the zoom stays at its locked value (text stays 16 px).
- Projector check: the grey, blue and purple fills differ by hue only.
- A long replay (hundreds of steps) shows no coordinate trouble.
- A full demo run under reduced motion: static red border, instant dim, no slide.
- Mock mode at 1.5 s per step, then `burst=10`: no stutter, no console errors.
- `.env` with `SECRET` and `x3` is untruncated; `README.md` too. A 644 px wide window.
- A real session with step numbers in the tens of thousands: the newest step stays in view for 30 steps in a row.
- With wifi off, `/v2/` loads and the Network panel shows only `localhost` requests (guards system fonts and `motion`). It is not automated: a scan of `ui/dist` for URLs would trip on React Flow's own attribution link.

## 12. Carried risks

Huge coordinates in very long sessions (checked manually). Fills that differ by hue only. AG-30 builds on the same stable rows, so its layout changes must keep them.

`secretSeen` can miss a real secret read. `recorder/store.py` records only the first matching token of a shell command as the step's file, so `cat README.md .env` marks the session in R1 but the step is not `sensitive` and the chip does not show. The intent accepts a page-state approximation; this is a wider hole than "a reload misses it", and AG-30's `flagged` is the real fix.

The unit tests cannot see a real browser. A click that pauses following, a sideways drag or a mid-slide zoom would pass every jsdom test, so the browser checks in section 11 stay required, not optional.
