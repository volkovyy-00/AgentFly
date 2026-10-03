# AG-30 design: long sessions stay light, with landmarks in reach

Ticket: AG-30 | Intent: `docs/superpowers/intents/2026-10-03-AG-30-long-sessions-intent.md` (approved 2026-10-03) | Path: architectural | Status: reviewed, owner answers recorded (2026-10-03)

This spec does not repeat the intent or the ticket. It resolves the intent's `(spec)` questions and fixes the design the plan will follow. Intent decisions are not reopened. It amends AG-29's "a box never moves" for the summary group, as the intent states.

## 1. What is built

The server keeps at most 500 steps per session plus all-time counters and the landmarks. `GET /api/steps?limit=N` adds `hidden`, `flagged` and `marked_order`. `/v2/` asks for `limit=20` and draws that window with, above it, one summary box and up to 5 flagged steps. The group moves with the window and never animates. The header chip and the `SECRET` chip come from the marking step.

Files: `recorder/memory.py`, `recorder/app.py`; `ui/src/graph/` (`types.ts`, `snapshot.ts`, `window.ts`, `layout.ts`, `camera.ts`, `nodes.tsx`, `tones.ts`, `useRecorder.ts`, `mock.ts`, `GraphView.tsx`), `ui/src/App.tsx`; `tests/test_app.py`, `tests/test_memory.py` (new), `tests/fixtures/window_golden.json` (new), vitest files beside each module; `ui/dist`, `HOOKS.md`, `README.md`, `ui/README.md`, `SPEC.md` § 6. No new dependency.

## 2. Resolved `(spec)` questions

| Question | Resolution |
|---|---|
| Group geometry; edge to the oldest step | Top to bottom: summary at row `first - 1 - k`, then the k flagged steps (ascending order), then the window (`first` is the oldest window row). Rows may be negative. The group exists only when `hidden.total > 0`. Group edges are a **chain** summary → f1 → … → fk (straight, bottom to top handle), id `group-edge:{order}` keyed on the target, so ids are stable: a newly flagged step only ever appends at the end (it has just left the window, so it is the newest outside it) and an eviction removes one edge and re-sources the next (same id, so React Flow updates it in place). A star was rejected: edges are drawn behind boxes, and a dimmed box is 0.4 opaque, so a star line to f3 would show through f1 and f2. **No edge from the summary or the last flagged step to the oldest window step**: its id would change every slide, and the group is a header, not a link in the chain. "Hung off the summary" means joined through it. |
| `limit` forms | Absent: legacy response. Present (test `is None`, not `str(x or "")`, which would turn `limit=` into "absent"): ASCII digits only (`str.isascii() and str.isdigit()`) and a value of at least 1, else 400 `{"detail": "bad limit"}`. That rejects `0`, `-1`, `abc`, `+5`, ` 5 `, `5_0` and an empty `limit=`. Above 50 counts as 50. Strip leading zeros first; an empty result means 0, so it is a 400; more than 4 digits left is above 50 without calling `int()` (Python 3.12 raises on 4,301+ digits, which would be a 500). A repeated key (`limit=5&limit=7`) resolves to the last value. With `all=1`, `limit` wins and `all` is ignored. An empty store with `limit` returns `{"session": null, "steps": [], "hidden": {all zeros}, "flagged": [], "marked_order": null}`. |
| A dropped lane box's edge | The page draws at most 15 file/host boxes (together) and 5 rule boxes. Over the cap, the box whose newest drawn toucher is oldest (`lastTouchRow`) goes first. Ties break by a fixed key that never changes as the window slides: a file is dropped before a host (hosts carry the block story), then the box with the lesser id is dropped first. (`anchorRow` is not a tie-break: it changes when an old toucher slides out, so the tie would flip with no touch.) There is no special case for secret files: protecting them keeps an old box in a slot and lets dropped boxes return with no touch (a simulation over random sessions found many such returns, and none under this rule). "Oldest" in the ticket is read as "touched longest ago". A box can therefore return only when something touches it again; it comes back as a fresh mount and replays its entry (fade, or spring for a rule), and a re-read of `.env` rightly pulses its ring. Trade-off: in a busy window the `.env` box can be dropped; the `SECRET` chip on the marking step and the header chip remain. Every edge into a dropped box is omitted; the step still shows its own text and chip. In practice the rule cap never binds (rules are R0 to R3), so tests use synthetic data. |
| Marking step and the 5 slots | The cap is 5 in total. The marking step takes a slot only once it is outside the window. While the marking step is still in the window, `flagged` holds up to 5 blocked or warned steps below the window; when the marking step leaves, it takes a slot and the oldest of them drops out. One pure function, `pick_flagged` (section 3). |
| The 500-step replay | Browser tab: `?mock=1&len=500&burst=10` (section 8). Server cap: pytest through `/hook` (section 9). Real server: loop `fake_agent.py --session s1` about 12 times (36 steps: marking at 2, a block every 3): a window-slide and mid-session-reload check, not the 500-step check. |

## 3. Server (`recorder/memory.py`, `recorder/app.py`)

**One class per session.** `_SessionMemory(cap)` holds: `steps` (a deque of at most `cap` step dicts), `counts` (all-time `total, read, shell, edit, tool, blocked, warned`), `evicted_flagged` (a deque, maxlen 5, of blocked or warned steps the cap pushed out) and `marking` (a copy of the marking step dict, or None). `MemorySteps(cap=500)` takes `cap` as a constructor parameter so the golden fixture can run with a small cap. One `clear()` and one cap rule.

**Hook path.** `append_step(session_id, step, marks=False)`: one append and a few counter increments. At `cap`, `popleft` by hand, and push the evicted step to `evicted_flagged` if its verdict is blocked or warned. If `marks`, store `marking = step`. No scans. `append_from_record` builds the dict as today and calls it. Step dicts are never mutated after appending, so counters cannot drift. `marking` is the same cleaned dict as the step, so no new data is stored (AGENTS.md: no contents, no secrets).

**Marking capture (`apply_rules`).** Read `was_marked = session.marked` before `session = mark(payload, session)`; pass `marks = session.marked and not was_marked` to `append_from_record`. In-memory only, no wait. After a server restart the session is already marked in `sessions.json`, so nothing is captured and `marked_order` is `null` (intent assumption).

**Snapshot with `limit`.** All of it runs inside the one `with self._lock` block; no helper re-takes the lock.

- `window` = last N of `steps`; `floor` = its first order.
- `hidden` = all-time `counts` minus the window's counts, for all seven keys.
- Candidates: reverse-scan `steps` below `floor` for blocked or warned (stop at 5), then `evicted_flagged` newest first.
- `flagged = pick_flagged(marking, candidates, floor, cap=5)`, a pure function on copies: take `marking` if its order is below `floor`; fill with candidates whose order differs from the marking order, newest first, deduping by order across both sources, up to 5 in total; sort ascending by order.
- `marked_order` = `marking["order"]` or `None`.

Without `limit` the response is unchanged: last 10, or all retained with `all=1` (up to 500).

**Restart.** `clear()` empties the counters but `next_step` continues from `sessions.json`, so after a restart "N earlier steps" counts only steps seen since. It is lower than the gap in order numbers, which is honest. `hidden.blocked` can exceed what `flagged` shows (the cap is for drawing, the counts are truthful). Neither is a bug.

## 4. API contract

```
GET /api/steps?limit=20
{ "session": "…", "steps": [ …last 20… ],
  "hidden": {"total": 590, "read": 0, "shell": 0, "edit": 0, "tool": 0, "blocked": 0, "warned": 0},
  "flagged": [ …≤5 steps, same shape, ascending… ],
  "marked_order": 3 | null }
```

`blocked` and `warned` in `hidden` are overlays on the kind counts, not a partition. The step shape is unchanged.

## 5. The page: data in

- `useRecorder` requests `/api/steps?limit=${WINDOW_SIZE}`, the one window constant (`window.ts`).
- `parseSnapshot` returns `hidden: Hidden | null`, `flagged: Step[]`, `markedOrder: number | null`. A missing `hidden` means no group (mock, legacy server); a missing `flagged` means none. `hidden` needs all seven integer keys, each at least 0; anything else, a non-array `flagged` or a non-integer `marked_order` makes the whole body invalid, so the page shows OFFLINE like any bad body. Individual `flagged` elements go through the step parser and an invalid one is dropped, like a bad window step.
- The reducer **replaces** `hidden`, `flagged` and `markedOrder` each poll; `merge()` still owns window steps and their rows. An unchanged poll returns the same state object (counts compared key by key, flagged by `sameStep`). Reset on session change, "New session" and backwards numbering, as today.
- `secretSeen`: set when `markedOrder !== null`, with the old "first `sensitive` step seen" rule as a fallback (so a live secret read after a restart still raises the chip). Sticky until reset. Timing: if the marking step is appended in this poll, the chip uses that step's quiet/delay; else on the first response it is quiet; else it appears live with no delay.

## 6. Layout and camera

- `layoutGraph(steps, group, markedOrder)`. Window steps, their lane boxes and chain edges are as today. Only window steps call `touch()`; flagged steps and the summary never do, so `anchorRow` cannot flip when a step becomes flagged and `useBoxMotion` replays nothing.
- The summary node: id `summary`, type `summary`, x and width of a step box, one `b` source handle. Flagged nodes keep id `step:{order}` (so a step leaving the window keeps its mounted node), data `{step, flagged: true, marked}` where `step` is quiet (`quiet: true, slot: 0, of: 1`) with its group row. Window steps get `marked` from `markedOrder`. A flagged order that is also in the window is skipped (the window wins); a layout test asserts no node id appears twice.
- Group boxes and edges mount quiet (no fade, no draw-in); a group move is a position change of mounted nodes.
- Caps: after the touch pass, drop file/host boxes over 15 and rule boxes over 5 as in section 2, and omit their edges. `count` for a kept box is unchanged.
- `rowsOf(steps, groupRowCount = 0)` returns `first` = the summary row when a group exists; `groupRowCount` is `1 + k` (the summary plus the k flagged steps actually drawn, after the "window wins" skip), so a skipped step leaves no row gap and a summary with nothing flagged still counts. A flagged step that has just left the window takes the row it already had, so when the departing step becomes flagged nothing moves; when it does not, the whole group moves down one row. `followTarget` and `panExtent` are linear in `rows.first`, so they need no change and `TOP_PAD` lands above the summary. `hasAlarm` reads window steps only, so a step that slides out cannot raise a new alarm. The camera effect stays keyed on the newest row: an unchanged poll never moves it.
- Known and accepted: when the window slides, the group hops one row at once while the camera glides, so on a pane taller than about 1,300 px, or for a viewer scrolled to the group, the hop shows. It is not fixed here (a pinned summary is out of scope).

## 7. Nodes, chips, tones

- `StepBox`: window steps keep `BLOCKED` / `WARN`; flagged steps show `BLOCKED R1` / `WARN R1`; a `marked` step adds `SECRET` (both chips if also blocked). All use existing tone rows (`chipBlocked`, `chipWarned`, `chipSecret`).
- `SummaryBox`: new `summary` row in `tones.ts` (checked at 7:1 by `tones.test.ts`). Text: `N earlier steps`, then `(2 blocked, 1 warned)` if any, then `: 20 read, 16 shell, …` with zero counts dropped. It truncates; the tooltip carries the full text. 16 px floor.
- The header chip in `App.tsx` reads the reducer's `secretSeen`, unchanged.
- The summary box is never dimmed: it stays bright while flagged steps and group edges dim during a block.

## 8. Mock

- `windowOfMock(all, limit, cap, markedOrder)` returns the server's response shape for `all`, the steps shown so far (the caller slices the prefix); `markedOrder` is explicit (the steps carry no `marks` field) and is `null` until that step is within `shown`. `useRecorder` mock mode dispatches it. The default mock session marks step 40001; the long one marks its index-1 step. It takes the same `cap` parameter as the server.
- `?mock=1&len=N` (1 to 2000, else default) builds a deterministic long session: a marking read at index 1 and a blocked step about every 13 steps. `burst` works as today.

## 9. Tests

Python (`tests/test_app.py`, `tests/test_memory.py`):
- 600 steps through `TestClient` posting to `/hook`: 500 retained, newest order 600, `hidden.total` 590 for `limit=10`, the block at 7 and the marking step (order 3) both in `flagged`.
- `cat README.md .env` then `curl`: `marked_order` is the first step's order, only when `limit` is sent. `cat .env | curl`: one step, marking and blocked, appears once in `flagged`.
- `limit`: each bad form is a 400, including an empty `limit=`, `0` and `00` (400), 5,000 zeros (400), 5,000 zeros then `7` (returns 7), a 5,000-digit value (clamps to 50, not a 500) and a repeated key (last wins); 80 behaves as 50; `all=1` with `limit` returns the `limit` shape; no `limit` is unchanged (the existing contract test).
- Marking outside the window plus 5 blocked: the marking step and the newest 4. More than 5 evictions keep the newest 5. A marking step that was evicted and blocked appears once. `limit` above the retained count: `flagged` empty, `hidden` zero (no eviction).
- Restart: `marked_order` is `null` and `hidden.total` is below the newest order.
- Golden fixture: `tests/fixtures/window_golden.json` holds `cap` (8), steps (a `marks` flag on the marking step) and cases `{limit, expect: {window, hidden, flagged, marked_order}}`, including marking evicted, evicted and blocked, over 5 evictions and the cap-5 cut. Pytest loads it into `MemorySteps(cap=8)`.

Vitest:
- Same golden fixture through `windowOfMock`.
- `parseSnapshot`: absent, valid and malformed fields.
- Reducer: unchanged poll gives the same object; group replaced, not merged; SECRET SEEN timing for a reload, a live marking step and the fallback.
- Layout: window boxes never move; the group moves down one row per slide with the same ids, and nothing moves when the departing step becomes flagged; orders in the tens of thousands give the same geometry; a server-shaped 500-step snapshot gives at most 50 boxes; dropped boxes lose their edges; with 16 or more file/host boxes, including ties on a shared step, no box returns without a touch; flagged steps do not move `anchorRow`; no duplicate node ids.
- Nodes: chips per section 7; a node that moves from the window into the group replays nothing.
- GraphView: one `setViewport` per slide, none on an unchanged poll; the pan extent reaches the summary and every flagged step.
- Existing tests that change: the exact URL `'/api/steps'` in `App.test.tsx` and `useRecorder.test.tsx` becomes `'/api/steps?limit=20'`; the new parameters are optional with defaults (`layoutGraph(steps, group = null, markedOrder = null)`, `rowsOf(steps, k = 0)`, optional `group` and `markedOrder` on `GraphView`) so the ~24 existing `layoutGraph`/`rowsOf` calls compile unchanged; tests that use the default `MOCK_SESSION` (34 steps) now see a group and are updated. The 5-rule cap uses synthetic rule ids.
- AG-29's stability test in `layout.test.ts` is amended to the new rule: window boxes never move, the group moves with the window.

## 10. Docs and Jira

- `HOOKS.md` § "Live graph": `limit`, `hidden`, `flagged`, `marked_order`, the 500 cap, restart behaviour of counts, "counts can exceed what is drawn". Replace "last 10 cleaned steps" with the default-versus-`limit` description.
- `README.md` (the `/v2/` paragraph) and `ui/README.md` (the 20-step line, the last-10-per-poll line, the mock `len` option and its `hidden`/`flagged`).
- `SPEC.md` § 6, three sentences change:
  1. "The new page draws the 20 most recent steps of the *current session* that it has seen (it keeps earlier steps between refreshes) …" becomes: draws the 20 most recent steps of the current session as the server returns them, with, above them, one summary box counting the earlier steps and up to 5 flagged steps (the step that made R1 mark the session, and the newest blocked or warned ones) joined to it in a column.
  2. "A file, website or rule is one box, level with the first drawn step that touches it." gains: at most 15 file and website boxes and 5 rule boxes are drawn; the one touched longest ago goes first. (The ticket authorises the window, the summary box and the rule-chip sentence; the owner approved this cap sentence too, 2026-10-03.)
  3. "A blocked step is joined by a dashed red line to a box for its rule (a warned step by a dashed purple line)." gains the authorised sentence: "an older flagged step names its rule in its chip instead of a box".
- Rebuild `ui/dist`; pass the stale-build check.
- Jira (approved 2026-10-03): AG-30's "hanging off it" becomes "joined through the summary box".

## 11. Manual checks (required)

- A 400 px pane: summary and chip truncation.
- A tall pane, and a viewer scrolled up to the group while steps arrive: see the hop.
- `?mock=1&len=500&burst=10`: the tab stays responsive.
- Real server: loop `fake_agent.py --session s1` about 12 times, reload mid-session: `SECRET` on the marking step, SECRET SEEN after the reload.

## 12. Carried risks and assumptions

- The `.env` file box can be dropped by the lane-box cap in a busy window; the `SECRET` chips remain.
- A server restart loses the chip on the marking step; the header chip survives via the fallback only if a sensitive step is seen. Counts restart at zero.
- Summary text may truncate on a narrow pane; the tooltip is the fallback.
- Python and TypeScript selection logic is duplicated; the golden fixture is what holds them together.
- The number of sessions held in memory is not capped (intent assumption).
- Plan order: server (independent), then page data, layout and camera, nodes and chips, mock, docs and `ui/dist`.
