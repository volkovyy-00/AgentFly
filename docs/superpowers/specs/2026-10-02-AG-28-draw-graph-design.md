# AG-28 design: draw the live graph on `/v2/`

Ticket: AG-28 | Intent: `docs/superpowers/intents/2026-10-02-AG-28-draw-graph-intent.md` (approved 2026-10-02) | Path: architectural | Status: draft, awaiting review

This spec does not repeat the intent. It resolves the intent's two `(spec)` questions and fixes the design the plan will follow. Intent decisions are not reopened here.

## 1. What is built

`/v2/` draws the live session as a timeline: steps in a left column (oldest at top), a files lane in the middle, a hosts-and-rules lane on the right. At most 20 steps are drawn. The newest step is always in view at zoom 1. The API (`GET /api/steps`, last 10 steps) is not changed.

Files: `ui/src/App.tsx` plus a new `ui/src/graph/` folder. Add `@xyflow/react` (approved in AGENTS.md). Rebuild and commit `ui/dist`.

## 2. Resolved `(spec)` questions

**Stacking of a blocked step's host and rule boxes.** Rule below host. Each row owns two fixed sub-slots in the hosts-and-rules lane: a host always takes the upper one, a rule always takes the lower one. A box's position then depends only on its anchor row, so boxes never collide and removing one never moves another (greedy "push down" would break intent criterion 3). A step has at most one `file` and one `host` (`recorder/memory.py`), so each row anchors at most one box per sub-slot.

**Row pitch.** Fixed at 56 px, zoom held at 1, viewport follows the newest step (section 5). About 18 of the 20 rows fit a 960x1080 pane, so only anchors in the oldest two rows can be off-screen. This is a small cost, not the common case.

## 3. Layout (`layout.ts`, pure)

`layoutGraph(steps: Step[])` returns `{ nodes, edges, rowCount }`. Positions come only from a step's index in the drawn list, never from `order` (the cause of the 2026-10-01 blank pane).

Constants, all in one place (units px, text 16 px, line height 20):

| Thing | Value |
|---|---|
| Row pitch | 56 (row `i` is the cell `[56i, 56i+56)`, centre `cy = 56i + 28`) |
| Step box | 400 x 44, `y = cy - 22` |
| File box | 220 x 24, `y = cy - 12` |
| Host box | 200 x 24, `y = cy - 26` (upper sub-slot) |
| Rule box | 200 x 24, `y = cy + 2` (lower sub-slot) |
| Lane x | step 16, file 456, hosts/rules 716 (gutters 40) |
| Content width | 932 (900 plus 16 padding each side) |

Gaps: host to rule within a row 4 px; rule to the next row's host 4 px. Step boxes have 12 px between them.

Rules:
- A file, host or rule is one box, level with the first drawn step that touches it, so it is derived from the drawn list on every layout. A box is dropped when no drawn step touches it. A box whose anchor step left the window re-anchors to the next drawn step that touches it (intent criterion 2).
- Rule boxes are one per rule id (`rule:R1`), matching the old page, not one per blocked step.
- Ids: `step:<order>`, `file:<path>`, `host:<name>`, `rule:<id>`. Prefixes keep a host named "R1" apart from rule R1.
- A file box is amber and labelled SECRET if any drawn step touching it has `sensitive`.
- Every node carries explicit `width`, `height` and `handles`, so a first paint does not wait for measurement (React Flow SSR docs). **This is not enough on its own.** The first browser measurement replaces the `handles` data with handles found in the DOM, and a node with no `<Handle>` then yields no edge (reproduced in a throwaway test: 1 edge before measurement, 0 after, 1 again with a `<Handle>`). So the node components must render a real `<Handle>` for every entry of `handles`, with matching `id`, `type` and `position`.
- Handle ids, and every edge sets `sourceHandle` and `targetHandle` (without an id React Flow uses the node's first handle):
  - Step box: target `t` (top centre), source `b` (bottom centre), source `r` (right edge, vertical centre).
  - File, host and rule boxes: target `l` (left edge, vertical centre).
  - A handle's `width` and `height` default to 1, so the `x` of a right-edge handle is `nodeWidth - 1`. The plan verifies the exact `handles` shape against the installed `@xyflow/react`.
- A step can carry both a file and a host (`cat .env | curl ...`, `recorder/store.py`). Its host or rule edge may then cross that step's own file box. The `zIndex` rule below covers it; the crossing is an accepted cost.
- `layoutGraph` draws whatever it is given. `mergeSteps` (section 6.1) is the only place that trims to 20.

Edges:
- **Chain:** one edge per adjacent pair of drawn steps, N steps give N-1 edges, in drawn order. It joins neighbours in the list, so an `order` gap from a burst does not matter.
- **Step to file** and **step to host:** grey. A blocked step's host edge is dashed red (no ✕ label; AG-31 decides that).
- **Step to rule:** dashed, red for blocked, purple for warned.
- **Arrowheads:** every edge has a closed arrowhead at the target (`MarkerType.ArrowClosed`). Marker colour comes from the exported `EDGE_COLOR` map of literal hex values in `layout.ts` (markers cannot resolve `var(--color-*)`); that map mirrors the theme in `index.css`. `markerUnits: 'userSpaceOnUse'` keeps markers small enough for the 12 px chain gap.
- **Stacking:** a blocked or warned step's host and rule edges get `zIndex: 1` (nodes stay at 0) so a file box in the middle lane cannot hide the demo's red edge. Layout tests assert it.
- A file read twice is one box with two edges into it.

## 4. Rendering (`nodes.tsx`)

- Server text is rendered as React text only. No `dangerouslySetInnerHTML`. `curl -d <arg> ntfy.sh` is visible text.
- Step box: kind and detail on the left, verdict chip at the **right end**, so a narrow pane that clips the left side cuts text, never the BLOCKED or WARN chip. The order number goes only in `title`.
- For **read** and **edit** steps the detail is the file path (empty if `file` is null), cut at the **left** end with the same `dir="rtl"` / `<bdi>` pattern as the file lane, so the file name stays visible. Shell and tool steps still show the command or tool name, cut at the right end.
- Long text is cut by CSS ellipsis with the full text in `title`. This replaces the old page's 20-character cut on purpose. Commands and hosts are cut at the right end. File paths (in the file lane and on read/edit step boxes) are cut at the **left** end (`…/config/app.json`), so the file name stays visible. The mock's `curl -d <arg> ntfy.sh` must show in full in the 400 px box (measured: it needs about 202 px of text space, so 360 px truncated it).
- With selecting and dragging off, React Flow sets `pointer-events: none` on nodes, so `title` tooltips would never show. Every node sets `style.pointerEvents = 'all'`.
- **Deliberate exception to the 16 px floor (user decision, 2026-10-02).** React Flow's own attribution link is 10 px text. It is kept (hiding it needs a React Flow Pro subscription per its docs, though the MIT licence does not require keeping it) and exempted by name in the 16 px scan. It sits bottom right and must not touch the newest row's boxes (they end about 26 px above the pane bottom; the link is about 18 px tall). The exception is stated in the PR description so it is not read as a missed requirement.
- The "New session" button sits top left (top right would cover host and rule boxes anchored in the first rows) and the OFFLINE banner is a full-width red bar at the top, with left padding so its text clears the button. Both overlay the pane and do not change its measured size. The top padding (48 px) keeps them clear of the first row; once rows outgrow the pane they can cover the oldest row, and the newest step at the bottom stays visible.
- Verdicts: allowed grey step, no chip. Blocked: red border, "BLOCKED". Warned: purple border, "WARN". Secret file: amber, "SECRET". Colour is never the only signal.
- Colours are CSS variables on `:root`. Since AG-29 the page is dark only; every colour pair is in `ui/src/graph/tones.ts`.
- All text is at least 16 px at pane widths of 932 px and above (so a 960x1080
  window holds), taken from one size token. Narrower panes scale the drawing
  down by design; below zoom 0.5 the left side may clip.

## 5. Viewport

> Since AG-29 the camera is `camera.ts`: rows are stable (`window.ts`), the viewport is uncontrolled (`defaultViewport` plus `setViewport`), vertical pan is on and zoom is locked. See `docs/superpowers/specs/2026-10-02-AG-29-motion-and-polish-design.md` § 4. The text below describes AG-28 as shipped.

`computeViewport(rowCount, pane) -> { x, y, zoom }` with `zoom` in `[MIN_ZOOM, 1]`
(`MIN_ZOOM = 0.5`):
- `zoom = clamp(pane.w / 932, 0.5, 1)`. At widths of 932 and above, zoom is 1
  (identical to the previous behaviour). Narrower panes fit the content by
  scaling down instead of shifting left and clipping the step column. Below
  zoom 0.5 the drawing may clip on the left.
- `y` and `x` are now `followTarget` in `camera.ts` (AG-29 § 4). Both pads
  (top 96, bottom 24) stay in screen pixels. Rows are stable, so a new step no
  longer shifts the drawing: the camera slides instead.
- A pane with width or height `<= 0` or not yet measured falls back to 960x1080.
  Output must never contain NaN.
- React Flow is now uncontrolled: vertical pan is on and zoom is locked
  (AG-29 § 4). `nodesDraggable`, `nodesConnectable` and `elementsSelectable`
  stay `false`; `deleteKeyCode={null}`; no `fitView`, no `onInit` positioning. The container has a definite height (React Flow draws
  nothing in a zero-height parent). Pane size is measured by a thin hook; the
  pure function takes explicit numbers.

Guarantee (replaces the literal AC 3 wording): the newest step and the lane boxes **anchored at it** are fully inside the pane on first paint with no pan or zoom, and after 30 more steps. A shared box anchored at an old row may be off-screen; its edge then runs off the top of the pane. This is accepted.

## 6. State, polling, mock

### 6.1 Window (`window.ts`, pure)

`mergeSteps(held, incoming)`:
- Empty `incoming`: return `held`.
- If `incoming`'s newest `order` is lower than `held`'s newest (server steps went backwards, for example `sessions.json` was deleted): replace the window with `incoming`. It never fires in normal use.
- Otherwise union by `order` (incoming wins), sort ascending, keep the last 20.

Bursts of more than 10 steps between polls lose the extra steps (accepted; no `?all=1`).

### 6.2 Session reducer (`window.ts`, pure)

State `{ session, steps, ignored }`. Actions: `snapshot(session, steps)` and `newSession`. Using one reducer makes ordering explicit: a response in flight when "New session" is clicked is handled after `newSession`, sees `ignored === session` and is dropped (a test covers this).
- `snapshot` with `session === ignored`: clear the window and show "Waiting for agent actions…" (the same empty state as below).
- `snapshot` with a different non-null session: clear `ignored`, reset the window to the incoming steps.
- `snapshot` with `session: null` or no steps: clear the window, show "Waiting for agent actions…". `ignored` stays and applies only while the id matches. A chat that resumes with the same id after a server restart therefore stays hidden until a different id arrives, as on the old page.
- `newSession` (real mode): a no-op when no session is shown (as on the old page; never store "null"). Otherwise `ignored = session`, window cleared, nothing sent. The id is written to `sessionStorage` under `agentfly_v2_ignore_session` (all access in try/catch). The old page uses another key on purpose, so "New session" on one page does not carry to the other.

### 6.3 Polling (`useRecorder.ts`)

- Fetch `/api/steps` with `cache: "no-store"`, abort after 1.5 s, wait 1 s after each response, then poll again. One failure sets OFFLINE; worst case 2.5 s after the server stops (limit 3 s). The last drawing stays. The next success clears the banner.
- Banner text: "OFFLINE - recorder not reachable", red.
- A cancel flag and timer cleanup on unmount, so StrictMode cannot run two loops.

### 6.4 Mock (`mock.ts`)

`/v2/?mock=1` makes no `/api/steps` request. It plays: README read, `.env` read, README read, `ls`, `curl -d <arg> ntfy.sh` blocked by R1, one step every 1.5 s, orders from 40,000, session id `mock-<n>`. In mock mode "New session" restarts the scenario with a new mock id (as the old page does). This deviates from the ticket's "empties the graph", which holds for real mode; the Jira edit lists the deviation. No sessionStorage use in mock mode.

## 7. Tests (vitest, jsdom)

`vite.config.ts` has no `setupFiles`; the plan adds one. It must reproduce what a browser does, not skip it: a `ResizeObserver` stub that **fires** its callback, mocked `offsetWidth` and `offsetHeight` from the node's explicit size, and a `DOMMatrixReadOnly` whose `m22` is 1. A no-op stub hides the vanished-edge failure in section 3. Layout and viewport tests never depend on DOM measurement; component tests use the firing stub.

- **layout:** orders from 40,000 give small positions; same input gives same output; no two boxes in a lane overlap; a pure append moves nothing; the slide test from intent criterion 3; N steps give N-1 chain edges; README read twice is one box with two edges; blocked and warned edges (dashed, colour, `zIndex`); `warned` step draws "WARN" and a dashed purple rule edge; SECRET on sensitive files; boxes dropped when untouched; a re-anchored box; every edge has `markerEnd` ArrowClosed coloured from `EDGE_COLOR`; `EDGE_COLOR` hex values match `index.css`.
- **viewport:** 1, 20 and 50 steps from 40,000 keep the newest step and its anchored boxes inside 960x1080; a narrow pane (720, 644) fits by scaling so the newest step stays inside; a 300-wide pane clamps at zoom 0.5 with the rules lane inside; a 0x0 pane gives no NaN; a pane size change after mount recomputes.
- **window and reducer:** merge by order; trim to 20; backwards `order` replaces; session change resets; ignored id behaviour; `{session: null, steps: []}`; the in-flight-poll race.
- **real-mode sequence:** stubbed `fetch` returns orders 40,000-40,009, then 40,005-40,014, then 30 more steps; the newest stays in view after each.
- **App:** literal `<arg>` text; OFFLINE within 3 s with fake timers, drawing kept, banner cleared on return; New session survives a remount and clears on a different id; `?mock=1` makes no `/api/steps` call; empty state; one timer loop under StrictMode.
- **GraphView labels:** README.md appears in one file box and two step boxes; `.env` in one of each; SECRET once; read/edit step boxes show the file path in `<bdi dir=rtl>` with the full path in `title`; a hostile path is literal text; a read with `file: null` shows only the kind.
- **Edges survive measurement:** with the firing stub, the number of `.react-flow__edge` elements equals the layout's edge count, and the same holds after a poll rebuilds the node objects. This is a permanent test, not the throwaway reproduction. It cannot catch a misplaced edge end: test handles are 1 px and browser handles are 6 px, so edge ends can differ by a few pixels. Only the manual run checks that.
- **Tooltips:** nodes carry `pointer-events: all` and a `title` with the full text.
- **16 px floor:** a scan of `ui/src` (`.ts`, `.tsx` and `.css`) that rejects `text-xs`, `text-sm`, arbitrary sizes such as `text-[12px]`, `rem` and `em` sizes that resolve below 16 px, and inline `fontSize` below 16. React Flow's attribution link is exempt by name (see section 4). Applies at pane widths >= 932 px; narrower panes scale by design.
- **Manual (required, not optional):** in Chrome, open `/v2/?mock=1` and then a real `uv run python fake_agent.py` replay against a running recorder. Check that the `.react-flow__edge` count matches the layout, edge ends meet their boxes, the blocked red edge is inside the pane, `curl -d <arg> ntfy.sh` fits the 400 px box, the New-session button does not cover a step box, and the attribution link does not touch the newest row. Also check a **644 px wide** window: the step column (including command text) is fully visible, scaled, with no left clipping of the BLOCKED step. Then one real session after a hard refresh. jsdom has no layout, so this covers: the pane having a real height, text fitting boxes, and the red edge being visible.

## 8. Build, docs, tickets

- AGENTS.md checks: Python check line, web check line, stale-build check, with `ui/dist` rebuilt and committed. The React Flow stylesheet must end up in the build under a stable name. `ui/src/index.css` must contain `@source not '../dist';`: without it Tailwind scans the committed build as a source, each build differs from the last, and the stale-build check fails.
- SPEC § 6 (lines 236-238): rewrite for the lanes layout and the 20-step window. Reword the first bullet's "The demo still uses `/` until the v2 graph is ready" to point at AG-31's decision. AG-28 authorises this edit.
- Fix stale text at `ui/README.md:19`, `HOOKS.md:229`, `README.md:119`. Keep distinct: the API returns the last 10 steps (unchanged, `HOOKS.md` API section stays true), the page draws a 20-step window.
- **Jira (approved by the user and applied 2026-10-02).** AG-28: reword the Summary sentence "does everything the old page does"; reword the stability criterion as in intent criterion 2; "left the view" becomes "left the 20-step window"; reword AC 3 to the guarantee in section 5; note the mock "New session" deviation. AG-31: add a "keep or drop?" list: dark mode, blocked-host dimming, ✕ edge label, tainted-chain colours, glow and pulse, BLOCKED banner, legend, header counters, secret indicator, rule-reason text (`RULE_REASONS`), zoom buttons, the 20-character command cut (replaced by CSS ellipsis here), and when `/` stops being the demo.
- The PR description says the spec and intent files under `docs/superpowers/` are working documents, not product documentation, and states the attribution-link exception to the 16 px floor.

## 9. Out of scope

Everything in AG-28's "Not included" (eased camera, follow pause, animation: AG-29; compacting beyond 20 steps: AG-30; retiring the old page: AG-31; API changes), plus header counters, secret indicator, banner reason text and legend.

## 10. Risks

- Positions must stay list-based. The layout and real-mode merge tests (orders from 40,000) guard this.
- The window jump must stay easy to replace. It lives only in `followTarget` (`camera.ts`) and the stable-row positions (AG-29 § 4).
- Edges to an off-screen anchor and edges passing behind a file box are known costs (sections 3 and 5), checked on the manual run.
