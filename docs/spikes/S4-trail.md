# S4: trail mock vs today's page
Status: done (as of 2026-10-16 00:49)
Result: PASS. The owner chose the trail, named nothing missing, and said the Why card carries the red-box-and-dashed-line-to-R1 moment. D15-A (trail as home) is confirmed. One request for the build: let the owner hide or resize the Why card.
Evidence: docs/spikes/S4-trail-mock.html (v3), S4-trail.png, S4-trail-half.png, S4-today-page.png; owner's answers below. No product code touched.
Needs owner: none
Details: see "## 2026-10-16 00:49" below.

## 2026-10-16 00:49

### Owner's verdict
Answers, in the owner's words (after seeing v3 at half-screen):
1. Trail or today's page? "trail"
2. What is missing? "nothing"
3. Does the Why card carry the old demo's red box with a dashed line to R1? "yes"
Extra, unprompted: "i would make possible to hide or resize the card".

### D15 result
**Pass: D15-A, the trail as home.** The owner picked the trail and named nothing missing. The lane graph moves to a "Graph" tab as D15-A describes.
For the build cards: the Why card must be hideable and resizable. The mock's card is fixed (about 480 px at full screen, 46% of the height when stacked) and has no control for this; the mock was not changed. How to hide or resize it (a drag handle, a collapse button, remembered between visits) is not decided; I did not guess.

### Notes for whoever builds it
- Keep the three things the owner reacted to: tinted idle blocks with only the selected block solid red, the rail from the secret read to the block, and the large red box with dashed lines to the host and `R1`.
- Half-screen (about 720 px) is the main use, so the one-screen stacked layout below 1080 px is the main layout, not a fallback.
- Not tested in this spike: live updates, motion, timestamps (the steps carry no time), and sessions that are not this synthetic one (one secret read, a block every 13 steps).

### Cleanup
The Vite dev server started for this card has been stopped.

## 2026-10-16 00:46

### v3: half-screen
The owner said v2 was "much better" but the UI will mostly sit on half the screen, and sent a screenshot at about 700 px wide: the header wrapped ("Live Trail" and the recorder text broke across lines), the page fell back to a stacked layout with the Why card below the fold, and the controls above the trail took about 450 px of height.
Changes (all in `docs/spikes/S4-trail-mock.html`):
- Below 1080 px the page is one screen: trail on top, Why card below (46% of the height), each scrolling on its own. Nothing scrolls the whole page.
- Header stays on one line: tabs and chips do not wrap; the step count and the recorder address hide below 1080 px, the recorder text hides below 760 px (the green dot stays, with a tooltip).
- The Why card measures its own width. When it is 560 px or wider, the chain runs left to right: `.env` read → folded steps → blocked box, with the dashed lines down to `ntfy.sh` and `R1` under the blocked box. Narrower (the 480 px side panel at full screen) it stays vertical.
- The key-hint line hides below 760 px.
Checked: 720 px window in Chrome (screenshot `S4-trail-half.png`: whole story, from the `.env` row to the messages sent, fits without scrolling the page) and 1440 px headless (`S4-trail.png`, unchanged layout). Detector: 0 findings. Not checked: windows narrower than about 600 px, and short windows (under 700 px tall).

## 2026-10-16 00:45

### v2: what changed and why
The owner said they did not like v1 (no reason given) and asked for the impeccable skill again. I ran its critique as two isolated reviewers (design review; detector and contrast evidence), then rebuilt the mock. The reviewers' ranked guesses at what was wrong with v1, in the order I acted on them:
1. **A wall of red.** 18 identical blocks were solid red rows, so no block stood out. Now every block is a tinted row with a red chip; only the selected one is solid red.
2. **The story was a small side diagram.** Step 2 → Step 14 was two rows with a folded line between. Now a thin amber-to-red rail runs in the number gutter from the `.env` read to the selected block, through the folded steps.
3. **The red-box moment was demoted.** The Why card's blocked box is now full width and large, with dashed red lines down to an `ntfy.sh` pill and a big `R1` pill (the old demo's shape). Title is 22 px.
4. **Noise.** Removed the "ALLOWED" chip on every group (26 of them) and the file lists in group rows. The pinned strip of 25 chips became two counter rows ("4 of 18", Prev / Next, keys `n` / `p`).
5. **Fixes in my own CSS** (flagged by the reviewers): removed 3 px coloured left borders; `aria-selected` on buttons became `aria-pressed`; keyboard focus ring now wins over the selected outline; Why card has `aria-live`; smallest text 12 px (was 11); muted text on red rows lightened (was 4.1:1 on hover); narrow-window layout below 1000 px; the three inert tabs are marked disabled.

Not done, on purpose: timestamps and a live "now" marker (the steps carry no time, and I will not invent it), and collapsing the 18 identical blocks into one row (the card asks for blocks pinned; say if you want repeats merged).
Detector: 0 findings after replacing a dashed CSS gradient with an SVG dashed line. Skipped the skill's snapshot to `.impeccable/` (outside this card's whitelist).

### Checked in a browser (Chrome, same tab as today's page)
Default view renders as in `docs/spikes/S4-trail.png`. `Next` ×3 moved to block 4 of 18 (Step 53): the card, the "4 of 18" counter and the rail all updated.

### What changed in the sections below
The 2026-10-16 00:40 section describes v1; the 00:45 section describes v2. Its "What to open", "The data" and "Limits" still hold. "What the trail shows" and "What I saw" are v1, so read them with the changes above.

## 2026-10-16 00:40

### What to open
- **Today's page** (dev server is running; `npm --prefix ui run dev`):
  `http://127.0.0.1:5173/?mock=1&len=240&burst=10`
  Wait about 40 s: mock mode adds 10 steps per 1.5 s tick, so 240 steps take 24 ticks.
- **Trail mock**: open `docs/spikes/S4-trail-mock.html` in Chrome (a plain file, no server needed).
  Click any red `#N` chip at the top or any red row to open its Why card. "Follow latest" jumps to the newest step.
  `?open=235` opens another block's card; `?view=latest` starts at the newest step.

### Screenshots (same Chrome tab, same 1543×784 viewport)
- `docs/spikes/S4-today-page.png`: today's page after the replay finished.
- `docs/spikes/S4-trail.png`: trail mock, Why card open on the first block.

### The data
- Source: `longSession(240)` in `ui/src/graph/mock.ts`, imported and run with `node --experimental-strip-types`, output dumped as JSON and pasted into the mock's `<script type="application/json">`. Nothing re-typed.
- 240 steps, orders 40000–40239. One `.env` read (order 40001), 18 blocked (R1), 7 warned (R2), the rest routine.
- Step numbers in the mock are `order − 40000 + 1`, so the `.env` read is **Step 2** and the first block is **Step 14**. The raw order is in each row's tooltip. (The card's example said "Step 14 read `.env` → Step 22"; this data has Step 2 → Step 14.)

### What the trail shows (v1; see 00:45 for the current mock)
- Routine runs between alarms fold into one row: "11 routine steps · 4 read · 2 edit · …" (26 groups). Click to expand.
- Blocks (red) and warnings (purple) stay as full rows, and every one is also a chip in a pinned strip at the top.
- The `.env` read is its own amber row.
- Why card for Step 14: title "Step 2 read `.env` → Step 14 tried `curl ntfy.sh` → R1". Below it a mini picture: amber `.env` box, a "11 routine steps between (3–13)" box, the red blocked box with dashed red lines to a blue `ntfy.sh` pill and a red `R1` pill (the old demo's shape). Then the real user and agent messages from `recorder/rules.py`, and the `agentfly rules draft` / `sudo agentfly rules apply` commands instead of an "allow once" button (D15, D19).
- Health strip and tab names (Live Trail, History, Rules, Graph) are shown only as labels. They do nothing.

### What I saw in v1 (mine, not the owner's)
- Today's page at 240 steps shows about 16 steps and 1 block at a time (the rest scroll off or are dimmed); the trail's first screen covers steps 1–79 (about 7 blocks and 2 warnings as rows), and its pinned strip lists all 18 blocks and 7 warnings.
- The Why card carries the red box and dashed lines, but they are small and sit in a side panel. Today's page draws them large, next to the box that was blocked, on the main canvas. That is the part to judge.
- The mock has no motion. Today's page animates new steps in. Not tested here.

### Limits of this spike
- Both pages play a synthetic session: one secret read, a block every 13 steps. Real sessions have more kinds of steps and fewer blocks, so grouping looks different.
- "Step 14" etc. are positions in this mock only.
- Mock layout was checked at 1440 px wide only.
- I used the impeccable skill's detector (0 findings) and my own review; I skipped its two-subagent critique and snapshot because the snapshot writes outside this card's whitelist. I fixed one wrong count ("232 routine steps between" counted blocks too).

### Owner's answers (fill in, in the owner's words)
1. Trail or today's page?
   > _pending_
2. What is missing?
   > _pending_
3. Does the Why card carry the old demo's "red box with a dashed line to R1" moment?
   > _pending_

### D15 result
Pending. Pass = the owner picks the trail, or names what it is missing → D15-A (trail as home). Fail → D15-C (keep the lane graph as home; spend G3 on History, Rules and the Why card around it).

### Cleanup
The Vite dev server started for this card is still running on port 5173 so the owner can look. Stop it with `pkill -f "vite --port 5173"`.
