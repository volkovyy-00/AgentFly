# AG-29 Motion and Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/v2/` a dark, high-contrast page whose camera glides down a stable timeline, with calm entry animations, a secret-read moment and one loud block moment, and nothing replaying on an unchanged poll.

**Architecture:** The window reducer gives every step a permanent canvas row, so positions never change and only the camera moves. The camera is uncontrolled and driven by a pure `camera.ts`. Animations are mount-driven (stable ids) from a pure timing table in `choreography.ts`. Every colour pair comes from one `tones.ts` table that a test checks for 7:1.

**Tech Stack:** React 19, `@xyflow/react` 12.12.0 (pinned), Tailwind 4, vitest + jsdom, `motion` (new, pinned exactly).

**Spec:** `docs/superpowers/specs/2026-10-02-AG-29-motion-and-polish-design.md` (read it first). Intent: `docs/superpowers/intents/2026-10-02-AG-29-motion-and-polish-intent.md`.

## Global Constraints

- Checks (AGENTS.md), run at the end of every phase:
  - Python: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
  - Web: `npm --prefix ui ci && npm --prefix ui run check`
  - Stale build: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"` (so rebuild and commit `ui/dist` first).
- Work order is fixed: camera slide (Phase 1), then animations (Phase 2), then theme (Phase 3). Each phase ends with all three checks green and `ui/dist` rebuilt and committed.
- `motion` is the only new dependency; pin it exactly. System fonts only (no CDN). No `dangerouslySetInnerHTML`.
- Text is at least 16 px (`textSize.test.ts` scan). Every text/background pair at rest is at least 7:1. Meaning is never by colour alone (word chips stay).
- A box's canvas position never changes while it is drawn. Animate inner elements only (never the React Flow node wrapper). Node, edge and handle ids stay stable. No `fitView`.
- Each animation 800 ms or less, except the 1.5 s dim hold. Reduced motion: every duration is 0 through one `ms()` helper, and a blocked step keeps a static red border.
- The camera slide is 400 ms or less, once per poll; an unchanged poll causes no animation and no camera move.
- `AGENTS.md`: the server and Python are not touched. Never print request bodies. Commit messages end with the `Co-Authored-By` line from the session's attribution reminder.
- Run commands from the repo root unless a step says `ui/`. Tests: `npm --prefix ui test -- <file>`.

## Review Focus

Failure modes the spec implies that most likely bite a person using this, most likely first. Each has a test in the task named in brackets.

1. The recorder's first response is empty and steps arrive later: those steps must animate, not be treated as first paint. [Task 5, `useRecorder.test.tsx`]
2. The server restarts and step numbering goes backwards: rows restart at 0, the view jumps, following resumes, and nothing crashes. [Task 2, Task 5]
3. A block with a rule and no host (an R0 block): the dim set, the edges and the layout must tolerate a null host. [Task 3, Task 9]
4. Ten steps arrive in one poll: exactly one camera slide, and the last entry starts by 350 ms. [Task 5, Task 8]
5. The viewer has panned away and the window slides or the pane resizes: the view is clamped in place, never teleported, and the text never changes size. [Task 4, Task 5]

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ui/src/graph/types.ts` | modify | `PlacedStep`, `SecretSeen` |
| `ui/src/graph/window.ts` | rewrite | stable rows, `epoch`, `secretSeen`, `quiet`/`slot`/`of` (pure) |
| `ui/src/graph/layout.ts` | modify | absolute rows, id helpers, `BoxMeta`, `hotIds`, `TOP_PAD` 96; later `enter` and wipe edges |
| `ui/src/graph/camera.ts` | create | pane/zoom helpers, target, extent, clamp, follow decision, gesture reducer (pure) |
| `ui/src/graph/viewport.ts` | delete | replaced by `camera.ts` |
| `ui/src/graph/motionPolicy.ts` | create | `useReducedMotion`, `useMs` |
| `ui/src/graph/GraphView.tsx` | rewrite | uncontrolled React Flow, Follow pill, mask, dim provider |
| `ui/src/graph/useRecorder.ts` | modify | sends `first`, returns `epoch`, `secretSeen`, replays the long mock |
| `ui/src/graph/choreography.ts` | create | timing table, `stagger`, `enterDelay` (pure) |
| `ui/src/graph/dim.tsx` | create | dim context, `useDimmed`, `useBlockDim` |
| `ui/src/graph/useBoxMotion.ts` | create | brighten / re-anchor / tick triggers for lane boxes |
| `ui/src/graph/WipeEdge.tsx` | create | edge with a first-run SVG mask wipe |
| `ui/src/graph/nodes.tsx` | rewrite | animated step and lane boxes |
| `ui/src/graph/tones.ts` | create | every colour pair as data |
| `ui/src/graph/mock.ts` | modify | `MOCK_SESSION` (34 steps), `parseBurst` |
| `ui/src/App.tsx`, `ui/src/index.css`, `ui/src/test-setup.ts`, `ui/package.json` | modify | band, chips, banner, tokens, `matchMedia` stub, `motion` |

---

## Execution units

Tasks 2 to 5 are one reviewed unit: `npm --prefix ui run check` is red between them because callers are only fixed in Task 5, so run single test files until Task 5 ends and review that unit as a whole. Tasks 1, 6, 13 and 15 need a real browser; use the Claude-in-Chrome tools (no new test dependency). Keep a single human checkpoint for the projector look in Task 15.

---

# Phase 1: camera

### Task 1: AG-28 first-paint check on a real session

The intent and AG-29 make this a prerequisite. No code changes.

- [ ] **Step 1: Run the recorder and the replay.** In one terminal: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`. In another: `uv run python fake_agent.py`. Open `http://localhost:8787/v2/` in Chrome at 960 px wide.
- [ ] **Step 2: Check.** The page draws the replayed session from the first poll, the newest step is fully in view, there are no console errors, and the red block and amber `.env` appear.
- [ ] **Step 3: Report.** Tell the user the result in the session. If it fails, STOP and say what failed: AG-29 depends on AG-28's first paint. Do not continue to Task 2.

### Task 2: Placed steps and the stable-row window

**Files:**
- Modify: `ui/src/graph/types.ts`, `ui/src/graph/testing.ts`
- Rewrite: `ui/src/graph/window.ts`, `ui/src/graph/window.test.ts`

**Interfaces:**
- Produces:
  - `PlacedStep extends Step { row: number; quiet: boolean; slot: number; of: number }`
  - `SecretSeen { quiet: boolean }`
  - `WindowState { session, steps: PlacedStep[], nextRow, secretSeen: SecretSeen | null, epoch, ignored }`
  - `WindowAction = { type: 'snapshot'; session; steps: Step[]; first?: boolean } | { type: 'newSession' }`
  - `initialWindowState(ignored?)`, `windowReducer`, `WINDOW_SIZE`
  - test helper `place(steps, firstRow = 0, over = {}) => PlacedStep[]`

- [ ] **Step 1: Add the types.** Append to `ui/src/graph/types.ts`:

```ts
/** A step plus where and how it first appeared on this page (window.ts sets these once). */
export interface PlacedStep extends Step {
  /** Canvas row, fixed when the step is first seen. */
  row: number
  /** From the page's first response: drawn without motion. */
  quiet: boolean
  /** Index within the poll that appended it. */
  slot: number
  /** How many steps that poll appended. */
  of: number
}

/** Set once a sensitive step is seen; `quiet` if it came in the first response. */
export interface SecretSeen {
  quiet: boolean
}
```

- [ ] **Step 2: Add the test helper.** In `ui/src/graph/testing.ts` add `import type { PlacedStep, Step } from './types'` (replace the existing import) and:

```ts
/** Steps as the window would place them: consecutive rows from `firstRow`. */
export function place(steps: readonly Step[], firstRow = 0, over: Partial<PlacedStep> = {}): PlacedStep[] {
  return steps.map((s, i) => ({ ...s, row: firstRow + i, quiet: false, slot: 0, of: 1, ...over }))
}
```

- [ ] **Step 3: Write the failing tests.** Replace `ui/src/graph/window.test.ts` entirely:

```ts
import { describe, expect, it } from 'vitest'
import { makeStep, stepsFrom } from './testing'
import { WINDOW_SIZE, initialWindowState, windowReducer, type WindowState } from './window'

const orders = (steps: { order: number }[]) => steps.map((s) => s.order)
const snap = (session: string | null, steps = stepsFrom(40000, 3), first = false) =>
  ({ type: 'snapshot', session, steps, first }) as const

describe('stable rows', () => {
  it('gives rows from 0 in order and keeps them as polls merge', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    s = windowReducer(s, snap('a', stepsFrom(40005, 10)))
    expect(orders(s.steps)).toEqual(Array.from({ length: 15 }, (_, i) => 40000 + i))
    expect(s.steps.map((x) => x.row)).toEqual(Array.from({ length: 15 }, (_, i) => i))
    expect(s.nextRow).toBe(15)
  })

  it('keeps each step on its row while the window slides', () => {
    let s = initialWindowState()
    for (const first of [40000, 40005, 40010, 40015, 40020, 40025, 40030]) {
      s = windowReducer(s, snap('a', stepsFrom(first, 10)))
    }
    expect(s.steps).toHaveLength(WINDOW_SIZE)
    expect(s.steps[0].order).toBe(40020)
    expect(s.steps[0].row).toBe(20)
    expect(s.steps.at(-1)?.row).toBe(39)
  })

  it('sorts incoming steps by order before assigning rows', () => {
    const reversed = [...stepsFrom(40000, 4)].reverse()
    const s = windowReducer(initialWindowState(), snap('a', reversed))
    expect(orders(s.steps)).toEqual([40000, 40001, 40002, 40003])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1, 2, 3])
  })

  it('tags a poll\'s new steps with slot and of', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    s = windowReducer(s, snap('a', stepsFrom(40001, 6)))
    expect(s.steps.map((x) => [x.slot, x.of])).toEqual([[0, 3], [1, 3], [2, 3], [0, 4], [1, 4], [2, 4], [3, 4]])
  })

  it('updates a known step in place and keeps its row', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(5)]))
    s = windowReducer(s, snap('a', [makeStep(5, { verdict: 'blocked' })]))
    expect(s.steps).toHaveLength(1)
    expect(s.steps[0]).toMatchObject({ order: 5, verdict: 'blocked', row: 0 })
  })

  it('ignores an unknown order below the newest held step', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(10), makeStep(12)]))
    s = windowReducer(s, snap('a', [makeStep(11), makeStep(12)]))
    expect(orders(s.steps)).toEqual([10, 12])
  })

  it('resets rows and bumps epoch when the server numbering goes backwards', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    const before = s.epoch
    s = windowReducer(s, snap('a', stepsFrom(0, 3)))
    expect(orders(s.steps)).toEqual([0, 1, 2])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1, 2])
    expect(s.epoch).toBe(before + 1)
  })

  it('does not mutate its input', () => {
    const incoming = stepsFrom(1, 3)
    windowReducer(initialWindowState(), snap('a', incoming))
    expect(orders(incoming)).toEqual([1, 2, 3])
  })
})

describe('first response (quiet)', () => {
  it('marks only steps appended with first: true', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3), true))
    expect(s.steps.every((x) => x.quiet)).toBe(true)
    s = windowReducer(s, snap('a', stepsFrom(40000, 5), false))
    expect(s.steps.map((x) => x.quiet)).toEqual([true, true, true, false, false])
  })

  it('never marks anything quiet by default', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(s.steps.every((x) => !x.quiet)).toBe(true)
  })
})

describe('secretSeen', () => {
  const secret = makeStep(40001, { kind: 'read', file: '.env', sensitive: true, command: null })

  it('is set by a sensitive step, stays, and records whether it was quiet', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(40000), secret], true))
    expect(s.secretSeen).toEqual({ quiet: true })
    s = windowReducer(s, snap('a', stepsFrom(40002, 30)))
    expect(s.secretSeen).toEqual({ quiet: true })
    const live = windowReducer(initialWindowState(), snap('a', [secret]))
    expect(live.secretSeen).toEqual({ quiet: false })
  })

  it('is null until a sensitive step is seen', () => {
    expect(windowReducer(initialWindowState(), snap('a')).secretSeen).toBeNull()
  })

  it('clears on New session and on a different session id', () => {
    let s = windowReducer(initialWindowState(), snap('a', [secret]))
    expect(windowReducer(s, { type: 'newSession' }).secretSeen).toBeNull()
    s = windowReducer(s, snap('b', [makeStep(1)]))
    expect(s.secretSeen).toBeNull()
  })
})

describe('windowReducer sessions', () => {
  it('shows a session and resets when the session id changes, bumping epoch', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    const epoch = s.epoch
    s = windowReducer(s, snap('b', stepsFrom(1, 2)))
    expect(s.session).toBe('b')
    expect(orders(s.steps)).toEqual([1, 2])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1])
    expect(s.epoch).toBe(epoch + 1)
  })

  it('returns the same state object when a poll changes nothing', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(windowReducer(s, snap('a'))).toBe(s)
    const full = windowReducer(s, snap('a', stepsFrom(40000, 40)))
    expect(windowReducer(full, snap('a', full.steps.slice(-10)))).toBe(full)
  })

  it('clears on {session: null, steps: []} and keeps the ignored id', () => {
    let s: WindowState = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap(null, []))
    expect(s).toMatchObject({ session: null, steps: [], ignored: 'a', secretSeen: null })
  })

  it('shows nothing for a session with no steps', () => {
    const s = windowReducer(initialWindowState(), snap('a', []))
    expect(s.session).toBeNull()
    expect(s.steps).toEqual([])
  })

  it('newSession hides the shown session, bumps epoch and sends nothing', () => {
    const shown = windowReducer(initialWindowState(), snap('a'))
    const s = windowReducer(shown, { type: 'newSession' })
    expect(s).toMatchObject({ session: null, steps: [], ignored: 'a', epoch: shown.epoch + 1 })
  })

  it('newSession with nothing shown is a no-op and never stores null', () => {
    const s = initialWindowState()
    expect(windowReducer(s, { type: 'newSession' })).toBe(s)
  })

  it('keeps hiding the ignored session, even when a response arrives late', () => {
    let s = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap('a', stepsFrom(40010, 10)))
    expect(s.steps).toEqual([])
    expect(s.ignored).toBe('a')
  })

  it('a different session id clears the ignored id and shows', () => {
    let s = windowReducer(initialWindowState('a'), snap('a'))
    s = windowReducer(s, snap('b'))
    expect(s.ignored).toBeNull()
    expect(s.session).toBe('b')
    expect(s.steps).toHaveLength(3)
  })

  it('starts hidden when the ignored id was stored by an earlier load', () => {
    const s = windowReducer(initialWindowState('a'), snap('a'))
    expect(s.steps).toEqual([])
  })
})
```

- [ ] **Step 4: Run it to see it fail.** `npm --prefix ui test -- src/graph/window.test.ts`. Expected: FAIL (missing exports/fields).

- [ ] **Step 5: Rewrite `ui/src/graph/window.ts`:**

```ts
import type { PlacedStep, SecretSeen, Step } from './types'

export const WINDOW_SIZE = 20

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  /** The drawn window: at most 20 steps, ascending by row. */
  steps: PlacedStep[]
  /** Next row to hand out in this session. */
  nextRow: number
  secretSeen: SecretSeen | null
  /** Bumps whenever the window is reset, so the camera knows to jump. */
  epoch: number
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | { type: 'snapshot'; session: string | null; steps: Step[]; first?: boolean }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], nextRow: 0, secretSeen: null, epoch: 0, ignored }
}

function resetFrom(state: WindowState, ignored: string | null): WindowState {
  return { ...initialWindowState(ignored), epoch: state.epoch + 1 }
}

/** Field-wise equality; keys come from the objects so a new field cannot drift. */
function sameStep(a: PlacedStep, b: PlacedStep): boolean {
  const keys = Object.keys(a) as (keyof PlacedStep)[]
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
}

function newestOrder(steps: readonly { order: number }[]): number {
  return steps.reduce((max, s) => Math.max(max, s.order), -Infinity)
}

interface Merged {
  steps: PlacedStep[]
  nextRow: number
  secretSeen: SecretSeen | null
  changed: boolean
}

/**
 * Merge a poll into the held window. A known order updates in place and keeps
 * its row; an order above the newest held step is appended with the next row;
 * an unknown order below the newest held step is ignored (placing it would move
 * a box). Steps are sorted by order first.
 */
function merge(base: WindowState, incoming: readonly Step[], first: boolean): Merged {
  const sorted = [...incoming].sort((a, b) => a.order - b.order)
  const byOrder = new Map(base.steps.map((s) => [s.order, s]))
  let top = newestOrder(base.steps)
  let changed = false
  const updates = new Map<number, PlacedStep>()
  const appended: Step[] = []

  for (const step of sorted) {
    const known = byOrder.get(step.order)
    if (known !== undefined) {
      const next: PlacedStep = { ...known, ...step }
      if (!sameStep(known, next)) {
        updates.set(step.order, next)
        changed = true
      }
    } else if (step.order > top) {
      appended.push(step)
      top = step.order
    }
  }

  const placed: PlacedStep[] = appended.map((step, slot) => ({
    ...step,
    row: base.nextRow + slot,
    quiet: first,
    slot,
    of: appended.length,
  }))
  if (placed.length > 0) changed = true

  let secretSeen = base.secretSeen
  const fresh = new Set(placed)
  for (const s of [...updates.values(), ...placed]) {
    if (s.sensitive && secretSeen === null) secretSeen = { quiet: fresh.has(s) && s.quiet }
  }
  if (secretSeen !== base.secretSeen) changed = true

  const steps = [...base.steps.map((s) => updates.get(s.order) ?? s), ...placed].slice(-WINDOW_SIZE)
  return { steps, nextRow: base.nextRow + placed.length, secretSeen, changed }
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === 'newSession') {
    if (state.session === null) return state
    return resetFrom(state, state.session)
  }

  const { session, steps, first = false } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hidden = session === null || session === ignored || steps.length === 0
  if (hidden) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return resetFrom(state, ignored)
  }

  // A new session, or numbering that went backwards (sessions.json deleted),
  // starts a fresh window.
  const restart = state.session !== session || newestOrder(steps) < newestOrder(state.steps)
  const base = restart ? resetFrom(state, ignored) : state
  const merged = merge(base, steps, first)

  if (!restart && !merged.changed && state.ignored === ignored) return state
  return {
    session,
    steps: merged.steps,
    nextRow: merged.nextRow,
    secretSeen: merged.secretSeen,
    epoch: base.epoch,
    ignored,
  }
}
```

- [ ] **Step 6: Run the tests.** `npm --prefix ui test -- src/graph/window.test.ts`. Expected: PASS. (Other test files fail to compile until Tasks 3 and 5; that is expected. Do not run the full suite yet.)

- [ ] **Step 7: Commit.**

```bash
git add ui/src/graph/types.ts ui/src/graph/testing.ts ui/src/graph/window.ts ui/src/graph/window.test.ts
git commit -m "AG-29: give each step a stable row in the window reducer"
```

### Task 3: Layout on absolute rows

**Files:**
- Modify: `ui/src/graph/layout.ts`, `ui/src/graph/layout.test.ts`

**Interfaces:**
- Consumes: `PlacedStep`.
- Produces:
  - `layoutGraph(steps: readonly PlacedStep[]): { nodes, edges }` (no `rowCount`)
  - `TOP_PAD = 96`
  - id helpers `stepId, fileId, hostId, ruleId, chainEdgeId, fileEdgeId, hostEdgeId, ruleEdgeId`
  - `BoxMeta { count; lastTouchRow; anchorRow }` on file/host/rule node data
  - `hotIds(step): Set<string>`

- [ ] **Step 1: Update the existing tests to compile, then add the new ones.** In `ui/src/graph/layout.test.ts`:
  1. Change the imports to bring in the new names and a wrapper. Replace the `layoutGraph` import with `layoutGraph as layoutPlaced` and add `TOP_PAD, hotIds, stepId, fileId, hostId, ruleId, hostEdgeId, ruleEdgeId, chainEdgeId, fileEdgeId` to the `./layout` import; change `import { makeStep } from './testing'` to `import { makeStep, place } from './testing'`. Directly after the imports add:

```ts
/** Rows 0.. in list order: the old behaviour, for tests that do not care about rows. */
const layoutGraph = (steps: readonly Step[]) => layoutPlaced(place(steps))
```
  2. Change the "lays out nothing" test to `expect(layoutGraph([])).toEqual({ nodes: [], edges: [] })`.
  2a. Box data now carries `count`, `lastTouchRow` and `anchorRow`, so in the test `marks a file secret when a drawn step touching it is sensitive` change the two `data` assertions from `toEqual` to `toMatchObject`:

```ts
    expect(node(layout, 'file:.env').data).toMatchObject({ path: '.env', sensitive: true })
    expect(node(layout, 'file:README.md').data).toMatchObject({ path: 'README.md', sensitive: false })
```
  3. Replace the test `moves a box to the next drawn step that touches it` with:

```ts
  it('re-anchors a box to the next drawn step that touches it, keeping rows', () => {
    const steps = [makeStep(1, { file: 'f' }), makeStep(2), makeStep(3, { file: 'f' })]
    expect(node(layoutGraph(steps), 'file:f').position.y).toBe(centre(0) - 12)
    const slid = layoutPlaced(place(steps.slice(1), 1))
    expect(node(slid, 'file:f').position.y).toBe(centre(2) - 12)
    expect(node(slid, 'step:3').position.y).toBe(centre(2) - STEP_H / 2)
  })
```
  4. Replace the test `a window slide shifts every row; only a box whose anchor left moves on its own` with:

```ts
  it('a window slide moves nothing except a box whose anchor left', () => {
    const base: Step[] = busy(20).map((s): Step => ({ ...s, file: null, host: null, rule: null }))
    base[0] = { ...base[0], file: 'shared.txt' }
    base[19] = { ...base[19], file: 'shared.txt' }
    base[5] = { ...base[5], host: 'h.com' }
    const before = layoutPlaced(place(base))
    const after = layoutPlaced([...place(base.slice(1), 1), ...place([makeStep(40020)], 20)])

    expect(has(after, 'step:40000')).toBe(false)
    expect(after.edges.some((e) => e.id === 'file-edge:40000' || e.id === 'chain:40000:40001')).toBe(false)
    expect(node(after, 'file:shared.txt').position.y).toBe(centre(19) - 12)
    expect(edge(after, 'file-edge:40019').target).toBe('file:shared.txt')

    for (const id of ['step:40005', 'host:h.com', 'step:40019']) {
      expect(node(after, id).position, id).toEqual(node(before, id).position)
    }
    const changed = after.nodes.filter((n) => {
      const was = before.nodes.find((b) => b.id === n.id)
      return was !== undefined && (was.position.x !== n.position.x || was.position.y !== n.position.y)
    })
    expect(changed.map((n) => n.id)).toEqual(['file:shared.txt'])
  })
```
  5. Append these new tests at the end of the file:

```ts
describe('absolute rows', () => {
  it('positions come from step.row, not from list index or order', () => {
    const layout = layoutPlaced(place([makeStep(40000), makeStep(40001)], 1000))
    expect(node(layout, 'step:40000').position.y).toBe(centre(1000) - STEP_H / 2)
    expect(node(layout, 'step:40001').position.y).toBe(centre(1001) - STEP_H / 2)
  })

  it('keeps the top padding equal to the 96 px fade mask', () => {
    expect(TOP_PAD).toBe(96)
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../index.css'), 'utf8')
    expect(css).toMatch(/\.fade-top[^}]*96px/s)
  })
})

describe('box metadata', () => {
  it('counts drawn touchers and tracks the first and newest toucher rows', () => {
    const steps = [makeStep(1, { file: 'f' }), makeStep(2), makeStep(3, { file: 'f' }), makeStep(4, { file: 'f' })]
    const f = node(layoutPlaced(place(steps, 10)), 'file:f')
    expect(f.data).toMatchObject({ count: 3, anchorRow: 10, lastTouchRow: 13 })
  })

  it('counts hosts and rules too', () => {
    const steps = [
      makeStep(1, { host: 'h', rule: 'R1', verdict: 'blocked' }),
      makeStep(2, { host: 'h', rule: 'R1', verdict: 'blocked' }),
    ]
    const layout = layoutPlaced(place(steps))
    expect(node(layout, 'host:h').data).toMatchObject({ count: 2, anchorRow: 0, lastTouchRow: 1 })
    expect(node(layout, 'rule:R1').data).toMatchObject({ count: 2, anchorRow: 0, lastTouchRow: 1 })
  })

  it('keeps count level when a toucher leaves and a new one arrives', () => {
    const full = [makeStep(1, { file: 'f' }), makeStep(2, { file: 'f' }), makeStep(3)]
    const slid = [makeStep(2, { file: 'f' }), makeStep(3), makeStep(4, { file: 'f' })]
    const a = node(layoutPlaced(place(full)), 'file:f').data as { count: number; lastTouchRow: number }
    const b = node(layoutPlaced(place(slid, 1)), 'file:f').data as { count: number; lastTouchRow: number }
    expect(a.count).toBe(2)
    expect(b.count).toBe(2)
    expect(b.lastTouchRow).toBeGreaterThan(a.lastTouchRow)
  })
})

describe('hotIds', () => {
  it('names the blocked step, its host and rule boxes and their edges, with the same ids layout uses', () => {
    const step = makeStep(7, { verdict: 'blocked', host: 'ntfy.sh', rule: 'R1' })
    const layout = layoutPlaced(place([step]))
    const hot = hotIds(step)
    expect([...hot].sort()).toEqual(
      [stepId(7), hostId('ntfy.sh'), ruleId('R1'), hostEdgeId(7), ruleEdgeId(7)].sort(),
    )
    for (const id of hot) {
      expect(has(layout, id) || layout.edges.some((e) => e.id === id), id).toBe(true)
    }
  })

  it('tolerates a block with a rule and no host (an R0 block)', () => {
    const step = makeStep(8, { verdict: 'blocked', host: null, rule: 'R0' })
    const layout = layoutPlaced(place([step]))
    const hot = hotIds(step)
    expect([...hot].sort()).toEqual([ruleId('R0'), ruleEdgeId(8), stepId(8)].sort())
    for (const id of hot) {
      expect(has(layout, id) || layout.edges.some((e) => e.id === id), id).toBe(true)
    }
  })

  it('exposes the other id helpers in the same format as before', () => {
    expect([fileId('a'), chainEdgeId(1, 2), fileEdgeId(3)]).toEqual(['file:a', 'chain:1:2', 'file-edge:3'])
  })
})
```

- [ ] **Step 2: Run to see failures.** `npm --prefix ui test -- src/graph/layout.test.ts`. Expected: FAIL (compile errors / missing exports).

- [ ] **Step 3: Edit `ui/src/graph/layout.ts`.**
  - Change `import type { Step } from './types'` to `import type { PlacedStep, Step } from './types'`.
  - Set `export const TOP_PAD = 96` (was 48).
  - Replace everything from `export type StepNode` to the end of `Layout` with:

```ts
export const stepId = (order: number): string => `step:${order}`
export const fileId = (path: string): string => `file:${path}`
export const hostId = (host: string): string => `host:${host}`
export const ruleId = (rule: string): string => `rule:${rule}`
export const chainEdgeId = (from: number, to: number): string => `chain:${from}:${to}`
export const fileEdgeId = (order: number): string => `file-edge:${order}`
export const hostEdgeId = (order: number): string => `host-edge:${order}`
export const ruleEdgeId = (order: number): string => `rule-edge:${order}`

/** What a shared box knows about the drawn steps that touch it. */
// A `type`, not an `interface`: React Flow requires node data to be a
// Record<string, unknown>, and an interface has no implicit index signature (TS2344).
export type BoxMeta = {
  /** Drawn steps touching the box. */
  count: number
  /** Row of the newest drawn toucher; advances when the box is reused. */
  lastTouchRow: number
  /** Row of the first drawn toucher, where the box sits. */
  anchorRow: number
}

export type StepNode = Node<{ step: PlacedStep }, 'step'>
export type FileNode = Node<{ path: string; sensitive: boolean } & BoxMeta, 'file'>
export type HostNode = Node<{ host: string } & BoxMeta, 'host'>
export type RuleNode = Node<{ rule: string } & BoxMeta, 'rule'>
export type GraphNode = StepNode | FileNode | HostNode | RuleNode

export interface Layout {
  nodes: GraphNode[]
  edges: Edge[]
}

/** Ids of what stays bright while a blocked step dims everything else. */
export function hotIds(step: Step): Set<string> {
  const ids = new Set([stepId(step.order)])
  if (step.host !== null) {
    ids.add(hostId(step.host))
    ids.add(hostEdgeId(step.order))
  }
  if (step.rule !== null) {
    ids.add(ruleId(step.rule))
    ids.add(ruleEdgeId(step.order))
  }
  return ids
}

function touch(boxes: Map<string, BoxMeta>, key: string, row: number): void {
  const box = boxes.get(key)
  if (box === undefined) boxes.set(key, { count: 1, lastTouchRow: row, anchorRow: row })
  else {
    box.count += 1
    box.lastTouchRow = row
  }
}
```
  - Keep `handle`, `STEP_HANDLES`, `boxHandles`, `FILE_HANDLES`, `HOST_HANDLES`, `BASE`, `rowCentre` unchanged. Change `link()` to take `from: PlacedStep` and use `source: stepId(from.order)`.
  - Replace the whole `layoutGraph` function with:

```ts
/**
 * Pure layout. Positions come only from a step's `row` (fixed when first seen),
 * never from its place in the list or from `step.order`. A file, host or rule is
 * one box, level with the first step in the list that touches it.
 */
export function layoutGraph(steps: readonly PlacedStep[]): Layout {
  const files = new Map<string, BoxMeta>()
  const hosts = new Map<string, BoxMeta>()
  const rules = new Map<string, BoxMeta>()
  const secretFiles = new Set<string>()

  for (const step of steps) {
    if (step.file !== null) {
      touch(files, step.file, step.row)
      if (step.sensitive) secretFiles.add(step.file)
    }
    if (step.host !== null) touch(hosts, step.host, step.row)
    if (step.rule !== null) touch(rules, step.rule, step.row)
  }

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, index) => {
    const cy = rowCentre(step.row)
    nodes.push({
      id: stepId(step.order),
      type: 'step',
      position: { x: STEP_X, y: cy - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { step },
      handles: STEP_HANDLES,
      ...BASE,
    })

    const previous = steps[index - 1]
    if (previous !== undefined) {
      edges.push({
        id: chainEdgeId(previous.order, step.order),
        type: 'straight',
        source: stepId(previous.order),
        sourceHandle: 'b',
        target: stepId(step.order),
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
        markerEnd: arrow(EDGE_COLOR.chain),
      })
    }

    if (step.file !== null) {
      const secret = step.sensitive
      edges.push(
        link(
          fileEdgeId(step.order),
          step,
          fileId(step.file),
          { stroke: secret ? 'var(--color-secret)' : 'var(--color-aux)', strokeWidth: 2 },
          secret ? 'secret' : 'aux',
        ),
      )
    }
    if (step.host !== null) {
      const blocked = step.verdict === 'blocked'
      const elevate = blocked || step.verdict === 'warned'
      edges.push(
        link(
          hostEdgeId(step.order),
          step,
          hostId(step.host),
          blocked
            ? { stroke: 'var(--color-blocked)', strokeWidth: 2.5, strokeDasharray: '8 6' }
            : { stroke: 'var(--color-aux)', strokeWidth: 2 },
          blocked ? 'blocked' : 'aux',
          elevate ? 1 : undefined,
        ),
      )
    }
    if (step.rule !== null) {
      const warned = step.verdict === 'warned'
      edges.push(
        link(
          ruleEdgeId(step.order),
          step,
          ruleId(step.rule),
          {
            stroke: warned ? 'var(--color-warned)' : 'var(--color-blocked)',
            strokeWidth: 2.5,
            strokeDasharray: '8 6',
          },
          warned ? 'warned' : 'blocked',
          1,
        ),
      )
    }
  })

  for (const [path, meta] of files) {
    nodes.push({
      id: fileId(path),
      type: 'file',
      position: { x: FILE_X, y: rowCentre(meta.anchorRow) + FILE_DY },
      width: FILE_W,
      height: LANE_H,
      data: { path, sensitive: secretFiles.has(path), ...meta },
      handles: FILE_HANDLES,
      ...BASE,
    })
  }
  for (const [host, meta] of hosts) {
    nodes.push({
      id: hostId(host),
      type: 'host',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + HOST_DY },
      width: HOST_W,
      height: LANE_H,
      data: { host, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }
  for (const [rule, meta] of rules) {
    nodes.push({
      id: ruleId(rule),
      type: 'rule',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + RULE_DY },
      width: HOST_W,
      height: LANE_H,
      data: { rule, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }

  return { nodes, edges }
}
```
  - In `ui/src/index.css` add (needed by the test above; the rest of the CSS is Phase 3):

```css
.fade-top {
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 96px);
  mask-image: linear-gradient(to bottom, transparent 0, #000 96px);
}
```

- [ ] **Step 4: Run.** `npm --prefix ui test -- src/graph/layout.test.ts`. Expected: PASS. (Run only this file here. `tsc -b` and the full suite are red until Task 5 fixes the callers; Tasks 2 to 5 are one reviewed unit.)

- [ ] **Step 5: Commit.**

```bash
git add ui/src/graph/layout.ts ui/src/graph/layout.test.ts ui/src/index.css
git commit -m "AG-29: lay out on absolute rows with box counts and id helpers"
```

### Task 4: Pure camera, motion policy, matchMedia stub

**Files:**
- Create: `ui/src/graph/camera.ts`, `ui/src/graph/camera.test.ts`, `ui/src/graph/motionPolicy.ts`, `ui/src/graph/motionPolicy.test.tsx`
- Modify: `ui/src/test-setup.ts`, `ui/src/graph/usePaneSize.ts`
- Delete: `ui/src/graph/viewport.ts`, `ui/src/graph/viewport.test.ts`, `ui/src/graph/follow.test.ts`

**Interfaces:**
- Consumes: `layout` constants (`BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD`), `PlacedStep`.
- Produces:
  - `PaneSize`, `FALLBACK_PANE`, `MIN_ZOOM`, `SLIDE_MS = 400`, `easeOutCubic`, `resolvePane`, `zoomFor(width)`
  - `Rows { first; last }`, `rowsOf(steps)`, `followTarget(rows, pane): Viewport`, `panExtent(rows, pane): CoordinateExtent`, `clampViewport(vp, extent, pane): Viewport`
  - `hasAlarm(steps, afterRow)`, `decideMove(prev, next, following)`
  - `slideOptions(ms)`
  - `Gesture { following; moved }`, `GestureEvent` (`resume | start | move | end`), `gestureStep(g, e): { next: Gesture; reissue: boolean }`, `INITIAL_GESTURE`
  - `useReducedMotion()`, `useMs(): (n: number) => number`; global test helper `setReducedMotion(flag)`

- [ ] **Step 1: Write `camera.test.ts`:**

```ts
import { describe, expect, it } from 'vitest'
import {
  FALLBACK_PANE, INITIAL_GESTURE, MIN_ZOOM, SLIDE_MS, clampViewport, decideMove, easeOutCubic, followTarget,
  gestureStep, hasAlarm, panExtent, resolvePane, rowsOf, slideOptions, zoomFor, type Gesture,
} from './camera'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD, layoutGraph } from './layout'
import { makeStep, place, stepsFrom } from './testing'
import { initialWindowState, windowReducer, type WindowState } from './window'

const PANE = { width: 960, height: 1080 }

describe('zoomFor', () => {
  it.each([932, 960, 3000])('is 1 when the pane is at least as wide as the content (%i)', (w) => {
    expect(zoomFor(w)).toBe(1)
  })
  it('scales down to fit, with a floor', () => {
    expect(zoomFor(644)).toBeCloseTo(644 / CONTENT_W)
    expect(zoomFor(300)).toBe(MIN_ZOOM)
  })
})

describe('resolvePane', () => {
  it.each([
    { width: 0, height: 0 },
    { width: Number.NaN, height: Number.NaN },
    { width: -5, height: Infinity },
  ])('falls back to 960x1080 for an unmeasured pane %j', (pane) => {
    expect(resolvePane(pane)).toEqual(FALLBACK_PANE)
    const vp = followTarget({ first: 0, last: 19 }, pane)
    expect(Object.values(vp).every(Number.isFinite)).toBe(true)
  })
})

describe('followTarget', () => {
  it('starts at the top padding for a short session', () => {
    expect(followTarget({ first: 0, last: -1 }, PANE)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
    expect(followTarget({ first: 0, last: 4 }, PANE)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
  })

  it('puts the first drawn row at the top padding even when it is row 40,000', () => {
    const vp = followTarget({ first: 40000, last: 40004 }, PANE)
    expect(40000 * ROW_PITCH + vp.y).toBe(TOP_PAD)
  })

  it('follows the newest row once rows outgrow the pane', () => {
    const vp = followTarget({ first: 100, last: 119 }, PANE)
    expect(120 * ROW_PITCH + vp.y).toBe(PANE.height - BOTTOM_PAD)
  })

  it('scales and keeps the content inside a 644-wide pane', () => {
    const vp = followTarget({ first: 0, last: 4 }, { width: 644, height: 1080 })
    expect(vp.zoom).toBeCloseTo(644 / CONTENT_W)
    expect(vp.x).toBeCloseTo(0)
  })
})

describe('panExtent', () => {
  it('spans the drawn rows plus the pads, divided by zoom', () => {
    // A 600 px tall pane, so 20 rows at zoom 0.69 outgrow it and the pads show.
    const pane = { width: 644, height: 600 }
    const z = zoomFor(644)
    const [[x0, y0], [x1, y1]] = panExtent({ first: 100, last: 119 }, pane)
    expect(x0).toBeCloseTo(0)
    expect(x1).toBeCloseTo(644 / z)
    expect(y0).toBeCloseTo(100 * ROW_PITCH - TOP_PAD / z)
    expect(y1).toBeCloseTo(120 * ROW_PITCH + BOTTOM_PAD / z)
  })

  it('is at least as tall as the pane, so d3 never centres a short session', () => {
    const [[, y0], [, y1]] = panExtent({ first: 0, last: 2 }, PANE)
    expect(y1 - y0).toBeGreaterThanOrEqual(PANE.height)
    expect(y0).toBe(-TOP_PAD)
  })

  it('leaves no room to pan sideways', () => {
    const [[x0], [x1]] = panExtent({ first: 0, last: 30 }, PANE)
    expect(x1 - x0).toBeCloseTo(PANE.width)
  })

  it('has the follow target inside it, touching the bottom edge when rows outgrow the pane', () => {
    const rows = { first: 100, last: 119 }
    const vp = followTarget(rows, PANE)
    const [[, y0], [, y1]] = panExtent(rows, PANE)
    expect(-vp.y / vp.zoom).toBeGreaterThanOrEqual(y0)
    expect((PANE.height - vp.y) / vp.zoom).toBeCloseTo(y1)
  })
})

describe('clampViewport', () => {
  const rows = { first: 100, last: 119 }
  const extent = panExtent(rows, PANE)

  it('returns the same viewport when it is inside the extent', () => {
    const vp = followTarget(rows, PANE)
    expect(clampViewport(vp, extent, PANE)).toBe(vp)
  })

  it('pulls a viewer who scrolled above the first row back to the top, with no NaN', () => {
    const clamped = clampViewport({ x: 0, y: 9999, zoom: 1 }, extent, PANE)
    expect(-clamped.y).toBe(extent[0][1])
    expect(Number.isFinite(clamped.y)).toBe(true)
  })

  it('pulls a viewer who scrolled below the newest row back up', () => {
    const clamped = clampViewport({ x: 0, y: -99999, zoom: 1 }, extent, PANE)
    expect(-clamped.y + PANE.height).toBe(extent[1][1])
  })
})

describe('hasAlarm and decideMove', () => {
  const blocked = (row: number, quiet = false) =>
    place([makeStep(row, { verdict: 'blocked' })], row, { quiet })[0]

  it('sees a non-quiet blocked or warned step after a row, not a quiet or older one', () => {
    expect(hasAlarm([blocked(5)], 4)).toBe(true)
    expect(hasAlarm([blocked(5)], 5)).toBe(false)
    expect(hasAlarm([blocked(5, true)], 4)).toBe(false)
    expect(hasAlarm(place([makeStep(9, { verdict: 'warned' })], 9), 8)).toBe(true)
  })

  it('jumps on the first call', () => {
    expect(decideMove(null, { lastRow: 3, alarm: false }, true)).toEqual({ move: 'jump', following: true })
  })

  it('does nothing for an unchanged poll', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 3, alarm: false }, true).move).toBe('none')
    expect(decideMove({ lastRow: 3 }, { lastRow: 3, alarm: false }, false).move).toBe('none')
  })

  it('slides once when the newest row advances and the viewer is following', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 13, alarm: false }, true)).toEqual({ move: 'slide', following: true })
  })

  it('does not move a paused viewer, but a blocked or warned step resumes following', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 4, alarm: false }, false)).toEqual({ move: 'none', following: false })
    expect(decideMove({ lastRow: 3 }, { lastRow: 4, alarm: true }, false)).toEqual({ move: 'slide', following: true })
  })
})

describe('slideOptions', () => {
  it('uses a linear interpolation so the zoom never dips, and 400 ms', () => {
    expect(slideOptions((n) => n)).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
    expect(SLIDE_MS).toBeLessThanOrEqual(400)
  })
  it('is instant under reduced motion', () => {
    expect(slideOptions(() => 0).duration).toBe(0)
  })
  it('eases from 0 to 1', () => {
    expect(easeOutCubic(0)).toBe(0)
    expect(easeOutCubic(1)).toBe(1)
  })
})

describe('gestureStep', () => {
  const run = (g: Gesture, ...events: Parameters<typeof gestureStep>[1][]) =>
    events.reduce((acc, e) => {
      const out = gestureStep(acc.next, e)
      return { next: out.next, reissue: out.reissue }
    }, { next: g, reissue: false })

  it('a click with no movement does not pause following and asks for a slide to the target', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: true }, { type: 'end', user: true })
    expect(out.next.following).toBe(true)
    expect(out.reissue).toBe(true)
  })

  it('a real move pauses following and does not ask for a slide', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: true }, { type: 'move', user: true }, { type: 'end', user: true })
    expect(out.next.following).toBe(false)
    expect(out.reissue).toBe(false)
  })

  it('a programmatic move never pauses following or asks for a slide', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: false }, { type: 'move', user: false }, { type: 'end', user: false })
    expect(out.next.following).toBe(true)
    expect(out.reissue).toBe(false)
  })

  it('resume sets following again', () => {
    const paused = run(INITIAL_GESTURE, { type: 'move', user: true }).next
    expect(paused.following).toBe(false)
    expect(gestureStep(paused, { type: 'resume' }).next.following).toBe(true)
  })

  it('a click while paused asks for nothing', () => {
    const paused = run(INITIAL_GESTURE, { type: 'move', user: true }, { type: 'end', user: true }).next
    expect(run(paused, { type: 'start', user: true }, { type: 'end', user: true }).reissue).toBe(false)
  })
})

describe('the newest step stays in view as polls arrive (real-sized orders)', () => {
  const view = (state: WindowState, pane: { width: number; height: number }): boolean => {
    const rows = rowsOf(state.steps)
    const vp = followTarget(rows, pane)
    const layout = layoutGraph(state.steps)
    const newest = state.steps.at(-1)
    const box = layout.nodes.find((n) => n.id === `step:${newest?.order}`)
    if (box === undefined) return false
    const top = box.position.y * vp.zoom + vp.y
    const bottom = top + (box.height ?? 0) * vp.zoom
    const left = box.position.x * vp.zoom + vp.x
    const right = left + (box.width ?? 0) * vp.zoom
    return top >= 0 && bottom <= pane.height && left >= 0 && right <= pane.width
  }
  const polls = [40000, 40005, 40010, 40020, 40030, 40040].map((n) => stepsFrom(n, 10))

  it.each([PANE, { width: 644, height: 1080 }, { width: 960, height: 600 }])('in a %j pane through 50 steps', (pane) => {
    let state = initialWindowState()
    for (const steps of polls) {
      state = windowReducer(state, { type: 'snapshot', session: 's', steps })
      expect(view(state, pane), `after orders up to ${state.steps.at(-1)?.order}`).toBe(true)
    }
    expect(state.steps).toHaveLength(20)
  })
})

describe('rowsOf', () => {
  it('is empty for no steps and spans first to last otherwise', () => {
    expect(rowsOf([])).toEqual({ first: 0, last: -1 })
    expect(rowsOf(place(stepsFrom(1, 3), 7))).toEqual({ first: 7, last: 9 })
  })
})
```

- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/graph/camera.test.ts`. Expected: FAIL (module missing).

- [ ] **Step 3: Create `ui/src/graph/camera.ts`:**

```ts
import type { CoordinateExtent, Viewport } from '@xyflow/react'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD } from './layout'
import type { PlacedStep } from './types'

export interface PaneSize {
  width: number
  height: number
}

/** The 960x1080 half screen the page is designed for. */
export const FALLBACK_PANE: PaneSize = { width: 960, height: 1080 }

/** Floor for fit-to-width zoom; below this the step column may clip on the left. */
export const MIN_ZOOM = 0.5

export const SLIDE_MS = 400

export const easeOutCubic = (t: number): number => 1 - (1 - t) ** 3

function usable(n: number): boolean {
  return Number.isFinite(n) && n > 0
}

/** Replace an unmeasured (0x0, NaN) pane with the design size. */
export function resolvePane(pane: PaneSize): PaneSize {
  return {
    width: usable(pane.width) ? pane.width : FALLBACK_PANE.width,
    height: usable(pane.height) ? pane.height : FALLBACK_PANE.height,
  }
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n))
}

/** The one zoom the camera ever uses; min and max zoom are both set to it. */
export function zoomFor(width: number): number {
  return clamp(width / CONTENT_W, MIN_ZOOM, 1)
}

/** First and last drawn row, inclusive. `last < first` when nothing is drawn. */
export interface Rows {
  first: number
  last: number
}

export function rowsOf(steps: readonly PlacedStep[]): Rows {
  const first = steps[0]
  const last = steps.at(-1)
  if (first === undefined || last === undefined) return { first: 0, last: -1 }
  return { first: first.row, last: last.row }
}

/**
 * Where the camera sits while following: the newest row's bottom `BOTTOM_PAD`
 * above the pane bottom, but never so low that the first drawn row passes
 * `TOP_PAD`. Both pads are screen pixels.
 */
export function followTarget(rows: Rows, pane: PaneSize): Viewport {
  const { width, height } = resolvePane(pane)
  const zoom = zoomFor(width)
  const fromTop = TOP_PAD - rows.first * ROW_PITCH * zoom
  const fromBottom = height - BOTTOM_PAD - (rows.last + 1) * ROW_PITCH * zoom
  return { x: Math.min(0, width - CONTENT_W * zoom), y: Math.min(fromTop, fromBottom), zoom }
}

/**
 * The pan range in flow units: the drawn rows plus the pads (divided by zoom,
 * since the pads are screen pixels), and never shorter than the pane (d3
 * centres content that is shorter). The x range is exactly the visible width,
 * so there is nothing to pan sideways.
 */
export function panExtent(rows: Rows, pane: PaneSize): CoordinateExtent {
  const { width, height } = resolvePane(pane)
  const zoom = zoomFor(width)
  const target = followTarget(rows, pane)
  const x0 = -target.x / zoom + 0
  const top = rows.first * ROW_PITCH - TOP_PAD / zoom
  const bottom = Math.max((rows.last + 1) * ROW_PITCH + BOTTOM_PAD / zoom, top + height / zoom)
  return [
    [x0, top],
    [x0 + width / zoom, bottom],
  ]
}

/** React Flow never re-clamps an existing viewport, so we do it. Returns `vp` itself when nothing changes. */
export function clampViewport(vp: Viewport, extent: CoordinateExtent, pane: PaneSize): Viewport {
  const { height } = resolvePane(pane)
  const [[, top], [, bottom]] = extent
  const visibleTop = -vp.y / vp.zoom
  const lowest = Math.max(top, bottom - height / vp.zoom)
  const clamped = Math.min(lowest, Math.max(top, visibleTop))
  return clamped === visibleTop ? vp : { ...vp, y: -clamped * vp.zoom + 0 }
}

/** A blocked or warned step that is newer than `afterRow` and not from the first paint. */
export function hasAlarm(steps: readonly PlacedStep[], afterRow: number): boolean {
  return steps.some((s) => s.row > afterRow && !s.quiet && (s.verdict === 'blocked' || s.verdict === 'warned'))
}

export type Move = 'none' | 'jump' | 'slide'

/** What the camera does after a render. `prev` is null on the first call. */
export function decideMove(
  prev: { lastRow: number } | null,
  next: { lastRow: number; alarm: boolean },
  following: boolean,
): { move: Move; following: boolean } {
  if (prev === null) return { move: 'jump', following: true }
  if (next.lastRow === prev.lastRow) return { move: 'none', following }
  if (next.alarm) return { move: 'slide', following: true }
  return { move: following ? 'slide' : 'none', following }
}

/** Options for every slide. `linear` keeps the zoom locked; the default interpolation dips it mid-flight. */
export function slideOptions(ms: (n: number) => number): {
  duration: number
  ease: (t: number) => number
  interpolate: 'linear'
} {
  return { duration: ms(SLIDE_MS), ease: easeOutCubic, interpolate: 'linear' }
}

export interface Gesture {
  following: boolean
  /** True once a user move (not just a mousedown) happened in this gesture. */
  moved: boolean
}

export const INITIAL_GESTURE: Gesture = { following: true, moved: false }

export type GestureEvent =
  | { type: 'resume' }
  | { type: 'start'; user: boolean }
  | { type: 'move'; user: boolean }
  | { type: 'end'; user: boolean }

/**
 * d3 interrupts a running slide and reports a start on mousedown, before any
 * movement, so only a user `move` pauses following. A click with no movement
 * while following asks the caller to slide to the current follow target. It
 * does not rely on remembering the interrupted slide: React Flow reports the
 * end up to 150 ms late, so a slow click would find that memory already gone.
 */
export function gestureStep(g: Gesture, e: GestureEvent): { next: Gesture; reissue: boolean } {
  switch (e.type) {
    case 'resume':
      return { next: { ...g, following: true }, reissue: false }
    case 'start':
      return { next: e.user ? { ...g, moved: false } : g, reissue: false }
    case 'move':
      return e.user ? { next: { ...g, following: false, moved: true }, reissue: false } : { next: g, reissue: false }
    case 'end':
      if (!e.user) return { next: g, reissue: false }
      return { next: { ...g, moved: false }, reissue: !g.moved && g.following }
  }
}
```

- [ ] **Step 4: Fix `usePaneSize.ts`.** Change `import type { PaneSize } from './viewport'` to `from './camera'`.

- [ ] **Step 5: Delete the old camera files.**

```bash
git rm ui/src/graph/viewport.ts ui/src/graph/viewport.test.ts ui/src/graph/follow.test.ts
```

- [ ] **Step 6: Add the `matchMedia` stub.** Append to `ui/src/test-setup.ts`:

```ts
// jsdom has no matchMedia. This stub answers `prefers-reduced-motion` from a
// flag tests flip with setReducedMotion(), and notifies subscribers.
let reducedMotion = false
const mediaListeners = new Set<() => void>()

declare global {
  // eslint-disable-next-line no-var
  var setReducedMotion: (flag: boolean) => void
}

globalThis.setReducedMotion = (flag: boolean) => {
  reducedMotion = flag
  for (const listener of mediaListeners) listener()
}

window.matchMedia = ((query: string): MediaQueryList => ({
  get matches() {
    return reducedMotion && query.includes('prefers-reduced-motion')
  },
  media: query,
  onchange: null,
  addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
    mediaListeners.add(listener as () => void)
  },
  removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
    mediaListeners.delete(listener as () => void)
  },
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
```
  Also make sure a reduced-motion test cannot leak: add `afterEach(() => globalThis.setReducedMotion(false))` at the bottom of `test-setup.ts` and add `import { afterEach } from 'vitest'` at the top of the file (tsconfig does not include vitest's global types, so `tsc -b` needs the import).

- [ ] **Step 7: Write `motionPolicy.test.tsx`:**

```tsx
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useMs, useReducedMotion } from './motionPolicy'

describe('motion policy', () => {
  it('passes durations through by default', () => {
    const { result } = renderHook(() => useMs())
    expect(result.current(400)).toBe(400)
    expect(renderHook(() => useReducedMotion()).result.current).toBe(false)
  })

  it('returns 0 for every duration under reduced motion, and reacts to changes', () => {
    const { result } = renderHook(() => useMs())
    act(() => globalThis.setReducedMotion(true))
    expect(result.current(400)).toBe(0)
    expect(result.current(1)).toBe(0)
    act(() => globalThis.setReducedMotion(false))
    expect(result.current(400)).toBe(400)
  })
})
```

- [ ] **Step 8: Create `ui/src/graph/motionPolicy.ts`:**

```ts
import { useCallback, useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(listener: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {}
  const media = window.matchMedia(QUERY)
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}

function snapshot(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches
}

/** Our own hook: motion's MotionConfig keeps opacity animations, which is not "every change instant". */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

/** `ms(n)` is n, or 0 under reduced motion. Every duration and delay goes through it. */
export function useMs(): (n: number) => number {
  const reduced = useReducedMotion()
  return useCallback((n: number) => (reduced ? 0 : n), [reduced])
}
```

- [ ] **Step 9: Run.** `npm --prefix ui test -- src/graph/camera.test.ts src/graph/motionPolicy.test.tsx`. Expected: PASS.

- [ ] **Step 10: Commit.**

```bash
git add -A ui/src
git commit -m "AG-29: add the pure camera, gesture rules and motion policy"
```

### Task 5: Uncontrolled GraphView, Follow pill, top band, recorder plumbing

**Files:**
- Modify: `ui/src/graph/useRecorder.ts`, `ui/src/graph/useRecorder.test.tsx`, `ui/src/graph/GraphView.tsx`, `ui/src/graph/GraphView.test.tsx`, `ui/src/App.tsx`, `ui/vite.config.ts`
- Modify (type fix only): `ui/src/graph/nodes.tsx` if the compiler asks

**Interfaces:**
- Consumes: Tasks 2-4.
- Produces:
  - `useRecorder(mock): { steps: readonly PlacedStep[]; secretSeen: SecretSeen | null; epoch: number; offline: boolean; newSession }`
  - `<GraphView steps epoch />`

- [ ] **Step 1: Failing recorder tests.** Add to `ui/src/graph/useRecorder.test.tsx` inside `describe('useRecorder (real mode)', ...)`:

```tsx
  it('marks only the first successful response as quiet', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: 's', steps: stepsFrom(40000, 3) }))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 5) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true, true])
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true, true, false, false])
  })

  it('an empty first response still uses up "first", so later steps animate', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: null, steps: [] }))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 2) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([false, false])
  })

  it('a failed first poll does not use up "first"', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('refused'))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 2) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true])
  })

  it('bumps epoch when the server restarts and numbering goes backwards', async () => {
    const bodies: Body[] = [
      { session: 's', steps: stepsFrom(40000, 10) },
      { session: 's', steps: stepsFrom(0, 3) },
    ]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond(bodies[Math.min(call++, 1)])))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    const epoch = result.current.epoch
    await advance(POLL_GAP_MS)
    expect(result.current.epoch).toBe(epoch + 1)
    expect(result.current.steps.map((s) => s.row)).toEqual([0, 1, 2])
  })

  it('exposes secretSeen once a sensitive step arrives', async () => {
    const secret = { ...stepsFrom(40000, 1)[0], kind: 'read' as const, file: '.env', sensitive: true, command: null }
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: [secret] })))
    const { result } = renderHook(() => useRecorder(false))
    expect(result.current.secretSeen).toBeNull()
    await advance(0)
    expect(result.current.secretSeen).toEqual({ quiet: true })
  })
```
  And in the mock block add: `it('mock steps are never quiet', ...)` that renders `useRecorder(true)`, advances 0 ms, and expects `result.current.steps[0].quiet` to be `false`.

- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/graph/useRecorder.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Edit `useRecorder.ts`.**
  - Imports: `import { useCallback, useEffect, useReducer, useRef, useState } from 'react'` and `import type { PlacedStep, SecretSeen } from './types'` (drop the unused `Step` import if the compiler flags it).
  - Change the interface:

```ts
export interface Recorder {
  steps: readonly PlacedStep[]
  secretSeen: SecretSeen | null
  /** Bumps when the window resets; the graph remounts and the camera jumps. */
  epoch: number
  offline: boolean
  newSession: () => void
}
```
  - Add `const firstResponse = useRef(true)` next to the `mockRun` state. In `poll()`, replace the dispatch lines (after the `if (cancelled) return`) with:

```ts
        setOffline(false)
        const first = firstResponse.current
        firstResponse.current = false
        dispatch({ type: 'snapshot', session: snapshot.session, steps: snapshot.steps, first })
```
  - Change the return to:

```ts
  return {
    steps: state.steps,
    secretSeen: state.secretSeen,
    epoch: state.epoch,
    offline: mock ? false : offline,
    newSession,
  }
```

- [ ] **Step 4: Run.** `npm --prefix ui test -- src/graph/useRecorder.test.tsx`. Expected: PASS.

- [ ] **Step 5: Rewrite the GraphView tests.** Replace `ui/src/graph/GraphView.test.tsx` entirely. The mock wraps `useReactFlow` (to record every `setViewport` call) and `ReactFlow` (to capture the props), so the camera is tested without d3:

```tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Viewport } from '@xyflow/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SLIDE_MS, easeOutCubic, followTarget, panExtent, rowsOf } from './camera'
import { GraphView } from './GraphView'
import { layoutGraph } from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep, place, stepsFrom } from './testing'

const spy = vi.hoisted(() => ({
  calls: [] as { vp: Viewport; options: Record<string, unknown> | undefined }[],
  props: {} as Record<string, any>,
  rf: undefined as any,
}))

vi.mock('@xyflow/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@xyflow/react')>()
  const { createElement } = await import('react')
  return {
    ...actual,
    useReactFlow: () => {
      const rf = actual.useReactFlow()
      spy.rf = rf
      return {
        ...rf,
        setViewport: (vp: Viewport, options?: Record<string, unknown>) => {
          spy.calls.push({ vp, options })
          return rf.setViewport(vp, options)
        },
      }
    },
    ReactFlow: (props: Record<string, any>) => {
      spy.props = props
      // ReactFlow is a forwardRef component object, not a function: render it.
      return createElement(actual.ReactFlow as never, props)
    },
  }
})

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

const viewportTransform = (container: HTMLElement) =>
  (container.querySelector('.react-flow__viewport') as HTMLElement).style.transform

const view = (steps: ReturnType<typeof place>, epoch = 0) => <GraphView steps={steps} epoch={epoch} />

beforeEach(() => {
  spy.calls.length = 0
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('drawing', () => {
  it('draws the demo story with labels that do not depend on colour', async () => {
    const steps = place(MOCK_STEPS)
    const { container } = render(view(steps))
    await settle()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('SECRET')).toBeTruthy()
    expect(screen.getByText('R1')).toBeTruthy()
    expect(screen.getByText('ntfy.sh')).toBeTruthy()
    const count = (selector: string, text: string) =>
      [...container.querySelectorAll(selector)].filter((n) => n.textContent?.includes(text)).length
    expect(count('.react-flow__node-file', 'README.md')).toBe(1)
    expect(count('.react-flow__node-step', 'README.md')).toBe(2)
    expect(count('.react-flow__node-file', '.env')).toBe(1)
    expect(count('.react-flow__node-step', '.env')).toBe(1)
    expect(screen.getAllByText('SECRET')).toHaveLength(1)
    expect(container.querySelectorAll('.react-flow__node')).toHaveLength(layoutGraph(steps).nodes.length)
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
  })

  it('shows a read step file path cut at the left end, with the full path in title', async () => {
    const path = 'src/very/long/directory/path/to/a-file-name.ts'
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: path, command: null })])))
    await settle()
    expect(container.querySelector(`[title="1: read ${path}"]`)).not.toBeNull()
    const bdi = container.querySelector('.react-flow__node-step bdi')
    expect(bdi?.textContent).toBe(path)
    expect(bdi?.closest('[dir="rtl"]')).not.toBeNull()
  })

  it('shows a hostile file path as literal text on a read step', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: hostile, command: null })])))
    await settle()
    expect(screen.getAllByText(hostile).length).toBeGreaterThanOrEqual(1)
    expect(container.querySelector('img')).toBeNull()
  })

  it('a read step with no file renders without stray text or throwing', async () => {
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: null, command: null })])))
    await settle()
    expect(container.querySelector('.react-flow__node-step')?.textContent).toBe('read')
  })

  it('labels a warned step WARN', async () => {
    render(view(place([makeStep(1, { verdict: 'warned', rule: 'R1', host: 'x.com', command: 'curl x.com' })])))
    await settle()
    expect(screen.getByText('WARN')).toBeTruthy()
    expect(screen.queryByText('BLOCKED')).toBeNull()
  })

  it('keeps every edge after React Flow measures and after a poll rebuilds the node objects', async () => {
    const steps = place(MOCK_STEPS)
    const { container, rerender } = render(view(steps))
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
    rerender(view(steps.map((s) => ({ ...s }))))
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
  })

  it('shows server text literally, never as HTML', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(view(place([makeStep(1, { command: hostile })])))
    await settle()
    expect(screen.getByText(hostile)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('lets node tooltips fire: pointer events on and the full text in title', async () => {
    const long = `curl -d ${'x'.repeat(80)} very-long-host.example.com`
    const { container } = render(view(place([makeStep(40001, { command: long })])))
    await settle()
    expect((container.querySelector('.react-flow__node') as HTMLElement).style.pointerEvents).toBe('all')
    expect(container.querySelector(`[title*="${long}"]`)).not.toBeNull()
  })
})

describe('camera', () => {
  it('puts the camera at the top with few steps and follows the newest with many', async () => {
    const few = render(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(viewportTransform(few.container)).toBe('translate(0px,96px) scale(1)')
    few.unmount()
    const many = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(many.container)).toBe('translate(0px,-64px) scale(1)')
  })

  it('works with absolute rows far from 0', async () => {
    const { container } = render(view(place(stepsFrom(40000, 20), 40000)))
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
    expect(container.querySelectorAll('.react-flow__node').length).toBeGreaterThan(0)
  })

  it('never produces NaN for an unmeasured 0x0 pane', async () => {
    const { container } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
  })

  it('recomputes the camera, with a jump, when the pane is resized after mount', async () => {
    let paneHeight = 1080
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') {
        return { width: 960, height: paneHeight, x: 0, y: 0, top: 0, left: 0, right: 960, bottom: paneHeight, toJSON() {} }
      }
      return real.call(this)
    })
    const { container } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-64px) scale(1)')
    spy.calls.length = 0
    paneHeight = 700
    await act(async () => {
      globalThis.fireResizeObservers()
    })
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-444px) scale(1)')
    expect(spy.calls.at(-1)?.options).toBeUndefined()
  })

  it('scales the drawing to fit a 644-wide pane', async () => {
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') {
        return { width: 644, height: 1080, x: 0, y: 0, top: 0, left: 0, right: 644, bottom: 1080, toJSON() {} }
      }
      return real.call(this)
    })
    const { container } = render(view(place(stepsFrom(40000, 5))))
    await settle()
    expect(viewportTransform(container)).toContain('scale(0.69')
  })

  it('jumps (no options) on first paint and on an epoch change', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(spy.calls.at(-1)?.options).toBeUndefined()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(1, 2)), 1))
    await settle()
    expect(spy.calls.length).toBeGreaterThan(0)
    expect(spy.calls.every((c) => c.options === undefined)).toBe(true)
  })

  it('slides once with exactly the agreed options when a step arrives', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 4))))
    await settle()
    expect(spy.calls).toHaveLength(1)
    expect(spy.calls[0].options).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
  })

  it('does not move the camera for an unchanged poll', async () => {
    const steps = place(stepsFrom(40000, 3))
    const { rerender } = render(view(steps))
    await settle()
    spy.calls.length = 0
    rerender(view(steps))
    rerender(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(spy.calls).toHaveLength(0)
  })

  it('slides once for a burst of ten steps', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 5))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 15))))
    await settle()
    expect(spy.calls).toHaveLength(1)
  })

  it('slides instantly under reduced motion', async () => {
    globalThis.setReducedMotion(true)
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 4))))
    await settle()
    expect(spy.calls[0].options?.duration).toBe(0)
  })
})

describe('pan, zoom and Follow', () => {
  const userMove = () =>
    act(() => {
      spy.props.onMove(new MouseEvent('mousemove'), { x: 0, y: 0, zoom: 1 })
    })

  it('locks zoom, allows only vertical pan, and does not cull offscreen elements', async () => {
    const steps = place(stepsFrom(40000, 20))
    render(view(steps))
    await settle()
    const p = spy.props
    expect(p.zoomOnScroll).toBe(false)
    expect(p.zoomOnPinch).toBe(false)
    expect(p.zoomOnDoubleClick).toBe(false)
    expect(p.minZoom).toBe(p.maxZoom)
    expect(p.panOnDrag).toBe(true)
    expect(p.panOnScroll).toBe(true)
    expect(p.panOnScrollMode).toBe('vertical')
    expect(p.onlyRenderVisibleElements).toBeUndefined()
    expect(p.viewport).toBeUndefined()
    expect(p.translateExtent).toEqual(panExtent(rowsOf(steps), { width: 0, height: 0 }))
  })

  it('shows Follow only after a user move, not after a programmatic one', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    act(() => spy.props.onMove(null, { x: 0, y: 0, zoom: 1 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    userMove()
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('a paused viewer is not moved by a new step; clicking Follow slides back once', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    userMove()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40001, 20), 1)))
    await settle()
    expect(spy.calls.every((c) => c.options === undefined)).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Follow' }))
    const slides = spy.calls.filter((c) => c.options !== undefined)
    expect(slides).toHaveLength(1)
    expect(slides[0].vp).toEqual(followTarget(rowsOf(place(stepsFrom(40001, 20), 1)), { width: 0, height: 0 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
  })

  it('a blocked step resumes following with one slide, but a quiet one does not', async () => {
    const base = place(stepsFrom(40000, 20))
    const { rerender } = render(view(base))
    await settle()
    userMove()
    const blocked = place([makeStep(40020, { verdict: 'blocked', rule: 'R1', host: 'x.com' })], 20)
    spy.calls.length = 0
    rerender(view([...base.slice(1), ...blocked.map((s) => ({ ...s, quiet: true }))]))
    await settle()
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
    rerender(view([...base.slice(2), ...blocked, ...place([makeStep(40021, { verdict: 'blocked' })], 21)]))
    await settle()
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    expect(spy.calls.filter((c) => c.options !== undefined)).toHaveLength(1)
  })

  it('a click with no movement does not pause following and slides to the target if the camera is off it', async () => {
    const steps = place(stepsFrom(40000, 4))
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    rerender(view(steps))
    await act(async () => {
      await spy.rf.setViewport({ x: 0, y: -1, zoom: 1 })
    })
    spy.calls.length = 0
    act(() => spy.props.onMoveStart(new MouseEvent('mousedown'), { x: 0, y: 0, zoom: 1 }))
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: 0, zoom: 1 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    expect(spy.calls).toHaveLength(1)
    expect(spy.calls[0].options).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
    expect(spy.calls[0].vp).toEqual(followTarget(rowsOf(steps), { width: 0, height: 0 }))
  })

  it('a click when the camera is already on the target does nothing', async () => {
    render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    act(() => spy.props.onMoveStart(new MouseEvent('mousedown'), { x: 0, y: 0, zoom: 1 }))
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: 0, zoom: 1 }))
    expect(spy.calls).toHaveLength(0)
  })

  it('a single wheel notch pauses following, since React Flow reports only a start for it', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    act(() => spy.props.onMoveStart(new WheelEvent('wheel'), { x: 0, y: 0, zoom: 1 }))
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('does not resume following when the viewer pans back to the newest row by hand', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    userMove()
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: -64, zoom: 1 }))
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('clamps a paused viewer in place, with no easing, when the window slides', async () => {
    const first = place(stepsFrom(40000, 20), 100)
    const { rerender } = render(view(first))
    await settle()
    userMove()
    await act(async () => {
      await spy.rf.setViewport({ x: 0, y: -(90 * 56), zoom: 1 })
    })
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40010, 20), 110)))
    await settle()
    const last = spy.calls.at(-1)
    expect(last?.options).toBeUndefined()
    const extent = panExtent({ first: 110, last: 129 }, { width: 0, height: 0 })
    expect(-last!.vp.y).toBeGreaterThanOrEqual(extent[0][1])
  })
})
```

- [ ] **Step 6: Run to fail.** `npm --prefix ui test -- src/graph/GraphView.test.tsx`. Expected: FAIL (GraphView still controlled).

- [ ] **Step 7: Rewrite `ui/src/graph/GraphView.tsx`:**

```tsx
import { PanOnScrollMode, ReactFlow, ReactFlowProvider, useReactFlow, type Viewport } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  INITIAL_GESTURE, clampViewport, decideMove, followTarget, gestureStep, hasAlarm, panExtent, rowsOf,
  slideOptions, type Gesture, type GestureEvent,
} from './camera'
import { layoutGraph } from './layout'
import { useMs } from './motionPolicy'
import { FileBox, HostBox, RuleBox, StepBox } from './nodes'
import type { PlacedStep } from './types'
import { usePaneSize } from './usePaneSize'

// Module-level so React Flow does not see a new object on every render.
const nodeTypes = { step: StepBox, file: FileBox, host: HostBox, rule: RuleBox }

interface Props {
  steps: readonly PlacedStep[]
  /** Bumps when the window resets. The drawing remounts, so the camera jumps and every box enters afresh. */
  epoch: number
}

/** The drawing. The camera is uncontrolled: only `setViewport` moves it. */
export function GraphView({ steps, epoch }: Props) {
  return (
    <ReactFlowProvider key={epoch}>
      <Drawing steps={steps} />
    </ReactFlowProvider>
  )
}

function Drawing({ steps }: { steps: readonly PlacedStep[] }) {
  const { ref, pane } = usePaneSize()
  const rf = useReactFlow()
  const ms = useMs()
  const layout = useMemo(() => layoutGraph(steps), [steps])
  const { first, last } = rowsOf(steps)
  const rows = useMemo(() => ({ first, last }), [first, last])
  const target = useMemo(() => followTarget(rows, pane), [rows, pane])
  const extent = useMemo(() => panExtent(rows, pane), [rows, pane])

  const gesture = useRef<Gesture>(INITIAL_GESTURE)
  const [following, setFollowing] = useState(true)
  const previous = useRef<{ lastRow: number } | null>(null)
  const previousPane = useRef(pane)

  const send = useCallback((event: GestureEvent): boolean => {
    const { next, reissue } = gestureStep(gesture.current, event)
    gesture.current = next
    setFollowing(next.following)
    return reissue
  }, [])

  const slideTo = (vp: Viewport): void => {
    void rf.setViewport(vp, slideOptions(ms))
  }
  const jumpTo = (vp: Viewport): void => {
    void rf.setViewport(vp)
  }

  // After each step change: jump, slide or leave the camera alone.
  useEffect(() => {
    const was = previous.current
    const alarm = was !== null && hasAlarm(steps, was.lastRow)
    const decision = decideMove(was, { lastRow: last, alarm }, gesture.current.following)
    previous.current = { lastRow: last }
    if (decision.move === 'jump') {
      send({ type: 'resume' })
      jumpTo(target)
    } else if (decision.move === 'slide') {
      if (decision.following) send({ type: 'resume' })
      slideTo(target)
    }
  }, [last]) // eslint-disable-line react-hooks/exhaustive-deps

  // A pane resize while following jumps to the follow target.
  useEffect(() => {
    if (previousPane.current === pane) return
    previousPane.current = pane
    if (gesture.current.following) jumpTo(target)
  }, [pane]) // eslint-disable-line react-hooks/exhaustive-deps

  // A paused viewer is clamped in place (instantly) when the extent or zoom changes.
  useEffect(() => {
    if (gesture.current.following) return
    const vp = rf.getViewport()
    const kept = { x: target.x, y: (vp.y * target.zoom) / vp.zoom, zoom: target.zoom }
    const clamped = clampViewport(kept, extent, pane)
    if (clamped.x !== vp.x || clamped.y !== vp.y || clamped.zoom !== vp.zoom) void rf.setViewport(clamped)
  }, [extent, target]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={ref} data-testid="graph-pane" className="relative h-full w-full">
      <div className="fade-top h-full w-full">
        <ReactFlow
          nodes={layout.nodes}
          edges={layout.edges}
          nodeTypes={nodeTypes}
          defaultViewport={target}
          translateExtent={extent}
          minZoom={target.zoom}
          maxZoom={target.zoom}
          onMoveStart={(event) => {
            if (event === null) return
            send({ type: 'start', user: true })
            // React Flow reports the first wheel event as a start and a move only
            // from the second, so a single notch would read as a click.
            if (event.type === 'wheel') send({ type: 'move', user: true })
          }}
          onMove={(event) => {
            if (event !== null) send({ type: 'move', user: true })
          }}
          onMoveEnd={(event) => {
            const again = send({ type: 'end', user: event !== null })
            if (!again) return
            const now = rf.getViewport()
            if (now.x !== target.x || now.y !== target.y || now.zoom !== target.zoom) slideTo(target)
          }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          panOnDrag
          panOnScroll
          panOnScrollMode={PanOnScrollMode.Vertical}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling
          deleteKeyCode={null}
        />
      </div>
      {!following && (
        <button
          type="button"
          onClick={() => {
            send({ type: 'resume' })
            slideTo(target)
          }}
          className="absolute right-4 top-2 z-30 rounded border-2 border-ink bg-white px-3 text-base leading-6 font-semibold text-ink"
        >
          Follow
        </button>
      )}
    </div>
  )
}
```
  Notes for the implementer:
  - `react-hooks/exhaustive-deps` is not installed in this repo; the `eslint-disable` comments are harmless and may be dropped.
  - The `ReactFlow` import name `ReactFlow` must stay (the test mock wraps it).
  - If TypeScript rejects `PanOnScrollMode.Vertical` as the test's expected `'vertical'`, check the enum value is the string `'vertical'` (it is in 12.12.0).

- [ ] **Step 8: Update `ui/src/App.tsx`:**

```tsx
import { GraphView } from './graph/GraphView'
import { useRecorder } from './graph/useRecorder'

function App() {
  const mock = new URLSearchParams(window.location.search).get('mock') === '1'
  const { steps, epoch, offline, newSession } = useRecorder(mock)

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-canvas text-base text-ink">
      <GraphView steps={steps} epoch={epoch} />
      {steps.length === 0 && (
        <p className="pointer-events-none absolute inset-0 grid place-items-center text-base text-muted">
          Waiting for agent actions…
        </p>
      )}
      {offline && (
        <div
          role="alert"
          className="absolute inset-x-0 top-0 z-20 bg-blocked px-4 py-2 pl-48 text-center text-base font-bold text-white"
        >
          OFFLINE - recorder not reachable
        </div>
      )}
      <button
        type="button"
        onClick={newSession}
        className="absolute left-4 top-2 z-30 rounded border-2 border-ink bg-white px-3 text-base leading-6 font-semibold text-ink"
      >
        New session
      </button>
    </main>
  )
}

export default App
```
  (Unchanged except `epoch`. The band chips and banner animation come in Task 12.)

- [ ] **Step 9: Raise the test timeout.** In `ui/vite.config.ts` add `testTimeout: 15000,` to the `test` block: the first React Flow test in a file has timed out at 5 s under parallel load.
- [ ] **Step 10: Run everything in `ui/`.** `npm --prefix ui run check`. Expected: PASS. If `nodes.tsx` has a type error from `PlacedStep`, fix the import only (the component bodies are rewritten in Task 10). If a pre-existing `App.test.tsx` or `useRecorder.test.tsx` case breaks only because `steps` now carry extra fields, loosen that assertion to compare `order`.

- [ ] **Step 11: Commit.**

```bash
git add -A ui/src ui/vite.config.ts
git commit -m "AG-29: make the camera uncontrolled with pan, Follow and stable rows"
```

### Task 6: Phase 1 close (docs, build, checks)

**Files:**
- Modify: `SPEC.md` (§ 6), `docs/superpowers/specs/2026-10-02-AG-28-draw-graph-design.md` (§ 5), `ui/README.md`, `ui/dist/*`

- [ ] **Step 1: SPEC § 6.** In `SPEC.md`, in the bullet that says the page "draws the 20 most recent steps of the *current session* that it has seen (it keeps earlier steps between refreshes) and keeps the newest step in view", change the ending to "...and keeps the newest step in view unless the viewer has scrolled away; a Follow button returns." This one-sentence edit is authorised by the intent (AGENTS.md "stop and ask" is met).
- [ ] **Step 2: AG-28 spec § 5.** The spec's lines are wrapped, so read § 5 ("5. Viewport") of `docs/superpowers/specs/2026-10-02-AG-28-draw-graph-design.md` and edit by hand, not by matching one line. Under the heading add: "> Since AG-29 the camera is `camera.ts`: rows are stable (`window.ts`), the viewport is uncontrolled (`defaultViewport` plus `setViewport`), vertical pan is on and zoom is locked. See `docs/superpowers/specs/2026-10-02-AG-29-motion-and-polish-design.md` § 4. The text below describes AG-28 as shipped." Then fix what the note contradicts: the `computeViewport` y/x formulas (now `followTarget` in `camera.ts`), the "In steady state ... to be eased by AG-29" sentence (rows are stable), and the "React Flow is fully controlled" bullet (uncontrolled; pan on, zoom locked). Keep each rewrite to one or two sentences that point at AG-29 § 4.
- [ ] **Step 3: `ui/README.md`.** Read the "What the page draws" section (its lines are wrapped) and rewrite the sentences by hand: the camera follows the newest step (one slide per poll); the viewer can pan up and down, a Follow button returns, zoom is locked (at most 1; panes narrower than the content scale down, floor 0.5); layout and camera are pure functions in `layout.ts` and `camera.ts`; positions come from a step's stable row, never from its `order` or its place in the list. Also change the earlier "`viewport.ts`" mention, if any.
- [ ] **Step 4: Build.** `npm --prefix ui run build`.
- [ ] **Step 5: All checks.** Run the three commands from Global Constraints (the stale-build check must print nothing after you `git add ui/dist` and commit; run it after the commit).
- [ ] **Step 6: Manual browser check (record results).** jsdom cannot see these, so drive them in real Chrome with the Claude-in-Chrome tools (no new test dependency such as Playwright without asking the user: AGENTS.md). With the recorder and `fake_agent.py` running, open `/v2/` and check:
  - a quick click on the page does not show "Follow";
  - a click held for about 500 ms does not show "Follow" and the camera ends on the newest step;
  - a single wheel notch pauses following and shows "Follow", and the next poll does not move the view;
  - a drag pauses and shows "Follow"; "Follow" slides back; a sideways drag shifts nothing;
  - text stays 16 px throughout a slide (sample the viewport transform: scale stays 1);
  - the first row of a young session sits just under the top band; also open `/v2/?mock=1`;
  - no console errors, in particular no "two children with the same key".
- [ ] **Step 7: Commit.**

```bash
git add SPEC.md docs ui/README.md ui/dist
git commit -m "AG-29: phase 1 docs and rebuilt ui/dist"
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo stale-build-ok
```

---

# Phase 2: animations

### Task 7: Pin `motion`

**Files:** Modify `ui/package.json`, `ui/package-lock.json`; Create `ui/src/pins.test.ts`

- [ ] **Step 1: Write the failing test** `ui/src/pins.test.ts`:

```ts
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const pkg = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../package.json'), 'utf8')) as {
  dependencies: Record<string, string>
}

describe('pinned dependencies', () => {
  it.each(['@xyflow/react', 'motion'])('%s is pinned exactly (no ^ or ~)', (name) => {
    expect(pkg.dependencies[name]).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
```
- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/pins.test.ts`. Expected: FAIL for `motion` (undefined).
- [ ] **Step 3: Install.** `npm --prefix ui view motion version` (it reported 14.0.0 on 2026-10-02; if it now reports a newer one, still install 14.0.0 and tell the user), then `npm --prefix ui install --save-exact motion@14.0.0`. Check `ui/package.json` shows `"motion": "14.0.0"` with no caret.
- [ ] **Step 4: Run.** `npm --prefix ui test -- src/pins.test.ts` → PASS. Smoke the import: `node -e "import('motion/react').then(m=>console.log(typeof m.motion))"` run from `ui/` prints `object`.
- [ ] **Step 5: Commit.**

```bash
git add ui/package.json ui/package-lock.json ui/src/pins.test.ts
git commit -m "AG-29: add motion, pinned exactly"
```

### Task 8: The timing table

**Files:** Create `ui/src/graph/choreography.ts`, `ui/src/graph/choreography.test.ts`

**Interfaces:**
- Produces: `TIMING` (name to `{start, end}` ms, relative to a step's own start), `EXEMPT`, `MAX_MS = 800`, `STAGGER_MAX_MS = 80`, `LAST_START_MS = 350`, `DIM_HOLD_MS = 1500`, `stagger(slot, of)`, `enterDelay(step)`, `dur(span)`, type `Span`.

- [ ] **Step 1: Write `choreography.test.ts`:**

```ts
import { describe, expect, it } from 'vitest'
import {
  DIM_HOLD_MS, EXEMPT, LAST_START_MS, MAX_MS, STAGGER_MAX_MS, TIMING, dur, enterDelay, stagger,
} from './choreography'

describe('timing table', () => {
  it('ends every animation by 800 ms, except the dim hold and its restore', () => {
    for (const [name, span] of Object.entries(TIMING)) {
      if ((EXEMPT as readonly string[]).includes(name)) continue
      expect(span.start, name).toBeGreaterThanOrEqual(0)
      expect(span.end, name).toBeGreaterThan(span.start)
      expect(span.end, name).toBeLessThanOrEqual(MAX_MS)
    }
  })

  it('keeps the dim hold at 1.5 s and exempts only the hold and restore', () => {
    expect(dur(TIMING.dimHold)).toBe(DIM_HOLD_MS)
    expect(DIM_HOLD_MS).toBe(1500)
    expect([...EXEMPT].sort()).toEqual(['dimHold', 'dimOut'])
  })

  it('matches the spec table for the block sequence', () => {
    expect(TIMING.step).toEqual({ start: 0, end: 200 })
    expect(TIMING.borderWipe).toEqual({ start: 100, end: 350 })
    expect(TIMING.blockEdge).toEqual({ start: 250, end: 550 })
    expect(TIMING.ruleSpring).toEqual({ start: 450, end: 800 })
    expect(TIMING.dimIn).toEqual({ start: 0, end: 150 })
  })
})

describe('stagger', () => {
  it('is 0 for the first step and for a lone step (no division by zero)', () => {
    expect(stagger(0, 1)).toBe(0)
    expect(stagger(0, 5)).toBe(0)
    expect(stagger(0, 0)).toBe(0)
    expect(Number.isFinite(stagger(0, 1))).toBe(true)
  })

  it('starts the last step of any burst by 350 ms', () => {
    for (let of = 1; of <= 20; of++) {
      expect(stagger(of - 1, of), `of=${of}`).toBeLessThanOrEqual(LAST_START_MS)
    }
  })

  it('uses 80 ms per step until that would pass 350 ms', () => {
    expect(stagger(1, 3)).toBe(STAGGER_MAX_MS)
    expect(stagger(9, 10)).toBeCloseTo(LAST_START_MS)
  })
})

describe('enterDelay', () => {
  it('is 0 for a quiet step and the stagger otherwise', () => {
    expect(enterDelay({ quiet: true, slot: 2, of: 3 })).toBe(0)
    expect(enterDelay({ quiet: false, slot: 2, of: 3 })).toBe(160)
  })
})
```
- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/graph/choreography.test.ts`.
- [ ] **Step 3: Create `choreography.ts`:**

```ts
/** Every animation's timing in one pure table. Times are ms relative to a step's own start. */
export interface Span {
  start: number
  end: number
}

export const MAX_MS = 800
export const STAGGER_MAX_MS = 80
export const LAST_START_MS = 350
export const DIM_HOLD_MS = 1500

export const TIMING = {
  step: { start: 0, end: 200 },
  chain: { start: 150, end: 350 },
  edge: { start: 250, end: 450 },
  laneBox: { start: 250, end: 450 },
  secretRing: { start: 300, end: 800 },
  chip: { start: 300, end: 500 },
  borderWipe: { start: 100, end: 350 },
  blockEdge: { start: 250, end: 550 },
  ruleSpring: { start: 450, end: 800 },
  dimIn: { start: 0, end: 150 },
  dimHold: { start: 150, end: 1650 },
  dimOut: { start: 1650, end: 1950 },
  brighten: { start: 0, end: 300 },
  reanchor: { start: 0, end: 200 },
  banner: { start: 0, end: 300 },
} as const satisfies Record<string, Span>

/** The only entries allowed past 800 ms. */
export const EXEMPT = ['dimHold', 'dimOut'] as const

export const dur = (span: Span): number => span.end - span.start

/** Start offset of the `slot`-th of `of` steps that arrived in one poll. */
export function stagger(slot: number, of: number): number {
  if (of <= 1) return 0
  return slot * Math.min(STAGGER_MAX_MS, LAST_START_MS / (of - 1))
}

export function enterDelay(step: { quiet: boolean; slot: number; of: number }): number {
  return step.quiet ? 0 : stagger(step.slot, step.of)
}
```
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit.** `git add ui/src/graph/choreography.ts ui/src/graph/choreography.test.ts && git commit -m "AG-29: add the pure animation timing table"`

### Task 9: Per-element dim

**Files:** Create `ui/src/graph/dim.tsx`, `ui/src/graph/dim.test.tsx`

**Interfaces:**
- Consumes: `hotIds`, `TIMING`, `enterDelay`, `DIM_HOLD_MS`, `PlacedStep`.
- Produces: `DimState { active; hot }`, `DimContext`, `useDimmed(id): boolean`, `useBlockDim(steps, epoch, ms): DimState`.

- [ ] **Step 1: Write `dim.test.tsx`:**

```tsx
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBlockDim } from './dim'
import { hostEdgeId, hostId, ruleEdgeId, ruleId, stepId } from './layout'
import { makeStep, place } from './testing'
import type { PlacedStep } from './types'

type Props = { steps: PlacedStep[]; epoch: number; ms: (n: number) => number }
const same = (n: number) => n
const none = (): PlacedStep[] => []
const blocked = (row: number, over: Partial<PlacedStep> = {}): PlacedStep =>
  place([makeStep(100 + row, { verdict: 'blocked', host: 'ntfy.sh', rule: 'R1' })], row, over)[0]
const setup = (props: Props) => renderHook((p: Props) => useBlockDim(p.steps, p.epoch, p.ms), { initialProps: props })
const tick = (n: number) => act(() => void vi.advanceTimersByTime(n))

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useBlockDim', () => {
  it('dims for 1.5 s after the dim-in, naming what stays bright, then restores', () => {
    const { result } = setup({ steps: [blocked(0)], epoch: 0, ms: same })
    tick(0)
    expect(result.current.active).toBe(true)
    expect([...result.current.hot].sort()).toEqual(
      [stepId(100), hostId('ntfy.sh'), ruleId('R1'), hostEdgeId(100), ruleEdgeId(100)].sort(),
    )
    tick(1649)
    expect(result.current.active).toBe(true)
    tick(1)
    expect(result.current.active).toBe(false)
  })

  it('never dims for a quiet (first paint) blocked step', () => {
    const { result } = setup({ steps: [blocked(0, { quiet: true })], epoch: 0, ms: same })
    tick(5000)
    expect(result.current.active).toBe(false)
  })

  it('starts at the blocked step\'s own delay within a burst', () => {
    const { result } = setup({ steps: [blocked(2, { slot: 2, of: 3 })], epoch: 0, ms: same })
    tick(159)
    expect(result.current.active).toBe(false)
    tick(1)
    expect(result.current.active).toBe(true)
  })

  it('restarts the hold for a second block instead of stacking', () => {
    const first = blocked(0)
    const { result, rerender } = setup({ steps: [first], epoch: 0, ms: same })
    tick(1000)
    rerender({ steps: [first, blocked(1)], epoch: 0, ms: same })
    tick(0)
    expect(result.current.active).toBe(true)
    expect(result.current.hot.has(stepId(101))).toBe(true)
    tick(1649)
    expect(result.current.active).toBe(true)
    tick(1)
    expect(result.current.active).toBe(false)
  })

  it('ignores a blocked step it has already handled', () => {
    const steps = [blocked(0)]
    const { result, rerender } = setup({ steps, epoch: 0, ms: same })
    tick(2000)
    expect(result.current.active).toBe(false)
    rerender({ steps: [...steps], epoch: 0, ms: same })
    tick(0)
    expect(result.current.active).toBe(false)
  })

  it('tolerates a block with no host', () => {
    const step = place([makeStep(7, { verdict: 'blocked', host: null, rule: 'R0' })], 0)[0]
    const { result } = setup({ steps: [step], epoch: 0, ms: same })
    tick(0)
    expect([...result.current.hot].sort()).toEqual([ruleId('R0'), ruleEdgeId(7), stepId(7)].sort())
  })

  it('under reduced motion dims at once and still holds for 1.5 s', () => {
    const { result } = setup({ steps: [blocked(0)], epoch: 0, ms: () => 0 })
    tick(0)
    expect(result.current.active).toBe(true)
    tick(1499)
    expect(result.current.active).toBe(true)
    tick(1)
    expect(result.current.active).toBe(false)
  })

  it('clears at once when the epoch changes', () => {
    const { result, rerender } = setup({ steps: [blocked(0)], epoch: 0, ms: same })
    tick(0)
    expect(result.current.active).toBe(true)
    rerender({ steps: none(), epoch: 1, ms: same })
    tick(0)
    expect(result.current.active).toBe(false)
  })

  it('dims a block that is among the first steps of a new session', () => {
    const { result, rerender } = setup({ steps: none(), epoch: 0, ms: same })
    rerender({ steps: [blocked(0)], epoch: 1, ms: same })
    tick(0)
    expect(result.current.active).toBe(true)
  })
})
```
- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/graph/dim.test.tsx`.
- [ ] **Step 3: Create `dim.tsx`:**

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { DIM_HOLD_MS, TIMING, enterDelay } from './choreography'
import { hotIds } from './layout'
import type { PlacedStep } from './types'

export interface DimState {
  active: boolean
  /** Ids that stay bright while `active`. */
  hot: ReadonlySet<string>
}

const OFF: DimState = { active: false, hot: new Set() }

export const DimContext = createContext<DimState>(OFF)

/** True for a node or edge that should be dimmed right now. Applied per element, never on a container. */
export function useDimmed(id: string): boolean {
  const { active, hot } = useContext(DimContext)
  return active && !hot.has(id)
}

/**
 * Starts a dim for the newest non-quiet blocked step that newly appears. The
 * timer starts at that step's own entry delay. A second block restarts the
 * hold, so dims never stack. The hold is not scaled by `ms`: under reduced
 * motion the dim is instant but still lasts 1.5 s.
 */
export function useBlockDim(steps: readonly PlacedStep[], epoch: number, ms: (n: number) => number): DimState {
  const [state, setState] = useState<DimState>(OFF)
  const handled = useRef(-1)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const clear = useCallback(() => {
    for (const timer of timers.current) clearTimeout(timer)
    timers.current = []
  }, [])

  // Must stay above the steps effect: on a reset both run in one commit.
  useEffect(() => {
    clear()
    setState(OFF)
    handled.current = -1
  }, [epoch, clear])

  useEffect(() => {
    const was = handled.current
    handled.current = steps.at(-1)?.row ?? -1
    const block = steps.filter((s) => s.row > was && !s.quiet && s.verdict === 'blocked').at(-1)
    if (block === undefined) return
    clear()
    const start = ms(enterDelay(block))
    timers.current.push(
      setTimeout(() => setState({ active: true, hot: hotIds(block) }), start),
      setTimeout(() => setState(OFF), start + ms(TIMING.dimIn.end) + DIM_HOLD_MS),
    )
  }, [steps]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => clear, [clear])

  return state
}
```
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit.** `git add ui/src/graph/dim.tsx ui/src/graph/dim.test.tsx && git commit -m "AG-29: add the per-element block dim"`

### Task 10: Animated nodes and lane-box motion

**Files:**
- Create: `ui/src/graph/useBoxMotion.ts`, `ui/src/graph/useBoxMotion.test.tsx`, `ui/src/graph/nodes.test.tsx`
- Modify: `ui/src/graph/layout.ts`, `ui/src/graph/layout.test.ts`, `ui/src/graph/nodes.tsx` (rewrite), `ui/src/graph/GraphView.tsx`

**Interfaces:**
- Consumes: Tasks 3, 8, 9; `useMs`.
- Produces: `Enter { quiet; delay }` and `enterOf(step)` in `layout.ts`; `BoxMeta.enter`; `useBoxMotion(meta) => { reanchor, bump, tick }`; animated `StepBox`, `FileBox`, `HostBox`, `RuleBox`.

- [ ] **Step 1: Layout `enter` test.** Append to `layout.test.ts`:

```ts
describe('enter timing on shared boxes', () => {
  it('takes the quiet flag and delay from the anchor step', () => {
    const steps = place([makeStep(1, { file: 'f' }), makeStep(2, { file: 'f' })], 0, { quiet: false, slot: 1, of: 3 })
    const data = node(layoutPlaced(steps), 'file:f').data as unknown as { enter: { quiet: boolean; delay: number } }
    expect(data.enter).toEqual({ quiet: false, delay: 80 })
    const quiet = node(layoutPlaced(place([makeStep(1, { file: 'f' })], 0, { quiet: true })), 'file:f')
    expect((quiet.data as unknown as { enter: { quiet: boolean } }).enter.quiet).toBe(true)
  })
})
```
- [ ] **Step 2: Edit `layout.ts`.** Add `import { enterDelay } from './choreography'`. Add:

```ts
/** How a box or edge enters: nothing for a first-paint step, else after the step's stagger delay. */
export interface Enter {
  quiet: boolean
  delay: number
}

export const enterOf = (step: PlacedStep): Enter => ({ quiet: step.quiet, delay: enterDelay(step) })
```
  Add `enter: Enter` to `BoxMeta`. Change `touch` to take the step:

```ts
function touch(boxes: Map<string, BoxMeta>, key: string, step: PlacedStep): void {
  const box = boxes.get(key)
  if (box === undefined) {
    boxes.set(key, { count: 1, lastTouchRow: step.row, anchorRow: step.row, enter: enterOf(step) })
  } else {
    box.count += 1
    box.lastTouchRow = step.row
  }
}
```
  and in `layoutGraph` call `touch(files, step.file, step)`, `touch(hosts, step.host, step)`, `touch(rules, step.rule, step)`. Run `npm --prefix ui test -- src/graph/layout.test.ts` → PASS.
- [ ] **Step 3: `useBoxMotion` tests.** Create `useBoxMotion.test.tsx`:

```tsx
import { renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { describe, expect, it } from 'vitest'
import { useBoxMotion } from './useBoxMotion'

type Meta = { anchorRow: number; lastTouchRow: number; count: number }
const setup = (meta: Meta) => renderHook((m: Meta) => useBoxMotion(m), { initialProps: meta })
const base: Meta = { anchorRow: 5, lastTouchRow: 9, count: 3 }

describe('useBoxMotion', () => {
  it('starts at zero, also under StrictMode', () => {
    expect(setup(base).result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
    const strict = renderHook(() => useBoxMotion(base), { wrapper: StrictMode })
    expect(strict.result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
  })

  it('brightens without ticking when the newest toucher advances and count stays level (full window)', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 10, count: 3 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 0 })
  })

  it('brightens and ticks when the count rises', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 10, count: 4 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 1 })
  })

  it('a re-anchor alone fades in', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 7, lastTouchRow: 9, count: 2 })
    expect(result.current).toEqual({ reanchor: 1, bump: 0, tick: 0 })
  })

  it('a re-anchor and a new touch in the same poll: the brighten wins', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 7, lastTouchRow: 10, count: 3 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 0 })
  })

  it('a falling count changes nothing', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 9, count: 2 })
    expect(result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
  })
})
```
- [ ] **Step 4: Create `useBoxMotion.ts`:**

```ts
import { useEffect, useRef, useState } from 'react'
import type { BoxMeta } from './layout'

export interface BoxMotion {
  /** Times the box jumped to a new anchor row (fade it in). */
  reanchor: number
  /** Times it was reused (brighten it). */
  bump: number
  /** Times its count rose (tick the number). */
  tick: number
}

/**
 * Triggers for a lane box that is already mounted. Brighten follows the newest
 * toucher's row (a full window drops one toucher and adds one, so the count can
 * stay level); the number ticks only when the count rises; a re-anchor in the
 * same poll as a new touch is skipped: the brighten wins.
 */
export function useBoxMotion({ anchorRow, lastTouchRow, count }: Pick<BoxMeta, 'anchorRow' | 'lastTouchRow' | 'count'>): BoxMotion {
  const previous = useRef({ anchorRow, lastTouchRow, count })
  const [motion, setMotion] = useState<BoxMotion>({ reanchor: 0, bump: 0, tick: 0 })

  useEffect(() => {
    const was = previous.current
    previous.current = { anchorRow, lastTouchRow, count }
    const touched = lastTouchRow > was.lastTouchRow
    const moved = anchorRow !== was.anchorRow
    const risen = count > was.count
    if (!touched && !moved && !risen) return
    setMotion((m) => ({
      reanchor: m.reanchor + (moved && !touched ? 1 : 0),
      bump: m.bump + (touched ? 1 : 0),
      tick: m.tick + (risen ? 1 : 0),
    }))
  }, [anchorRow, lastTouchRow, count])

  return motion
}
```
- [ ] **Step 5: Node tests.** Create `nodes.test.tsx`:

```tsx
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { GraphView } from './GraphView'
import { makeStep, place } from './testing'

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

afterEach(cleanup)

const secretRead = (order: number) => makeStep(order, { kind: 'read', file: '.env', sensitive: true, command: null })
const blocked = (order: number) => makeStep(order, { verdict: 'blocked', host: 'ntfy.sh', rule: 'R1', command: 'curl x' })

describe('lane boxes', () => {
  it('shows xN from 2 up, with SECRET and the count beside an untruncated path', async () => {
    const { container } = render(<GraphView steps={place([secretRead(1), makeStep(2), secretRead(3), secretRead(4)])} epoch={0} />)
    await settle()
    const box = container.querySelector('.react-flow__node-file') as HTMLElement
    expect(box.textContent).toContain('x3')
    expect(screen.getByText('SECRET').className).toContain('shrink-0')
    expect(screen.getByText('x3').className).toContain('shrink-0')
    expect(box.querySelector('bdi')?.textContent).toBe('.env')
  })

  it('shows no count for a box touched once', async () => {
    render(<GraphView steps={place([secretRead(1)])} epoch={0} />)
    await settle()
    expect(screen.queryByText(/^x\d+$/)).toBeNull()
  })

  it('shows xN on host and rule boxes too', async () => {
    const { container } = render(<GraphView steps={place([blocked(1), blocked(2)])} epoch={0} />)
    await settle()
    expect(container.querySelector('.react-flow__node-host')?.textContent).toContain('x2')
    expect(container.querySelector('.react-flow__node-rule')?.textContent).toContain('x2')
  })

  it('rings a live secret read, not one from the first paint', async () => {
    const live = render(<GraphView steps={place([secretRead(1)])} epoch={0} />)
    await settle()
    expect(live.container.querySelector('[data-testid="ring"]')).not.toBeNull()
    live.unmount()
    const quiet = render(<GraphView steps={place([secretRead(1)], 0, { quiet: true })} epoch={0} />)
    await settle()
    expect(quiet.container.querySelector('[data-testid="ring"]')).toBeNull()
  })
})

describe('step boxes', () => {
  it('draws a border wipe for blocked and warned steps and not for allowed ones', async () => {
    const steps = place([makeStep(1), blocked(2), makeStep(3, { verdict: 'warned', rule: 'R2', command: 'rm x' })])
    const { container } = render(<GraphView steps={steps} epoch={0} />)
    await settle()
    const wipes = (id: string) => container.querySelectorAll(`.react-flow__node[data-id="${id}"] [data-testid="border-wipe"]`).length
    expect([wipes('step:1'), wipes('step:2'), wipes('step:3')]).toEqual([0, 1, 1])
  })

  const wipeClip = (container: HTMLElement) =>
    (container.querySelector('[data-testid="border-wipe"]') as HTMLElement).style.clipPath

  it('shows the full red border for a first-paint step', async () => {
    const { container } = render(<GraphView steps={place([blocked(1)], 0, { quiet: true })} epoch={0} />)
    await settle()
    expect(wipeClip(container)).not.toContain('100%')
  })

  it('shows the full red border under reduced motion, not hidden mid-wipe', async () => {
    globalThis.setReducedMotion(true)
    const { container } = render(<GraphView steps={place([blocked(1)])} epoch={0} />)
    await settle()
    expect(wipeClip(container)).not.toContain('100%')
  })
})

describe('dim', () => {
  const dimmed = (container: HTMLElement, id: string) =>
    container.querySelector(`[data-id="${id}"] [data-dim]`)?.getAttribute('data-dim')

  it('dims the boxes except the blocked step, its host and its rule (edges are covered in Task 11)', async () => {
    const steps = place([makeStep(1, { kind: 'read', file: 'README.md', command: null }), blocked(2)])
    const { container } = render(<GraphView steps={steps} epoch={0} />)
    await settle()
    expect(dimmed(container, 'step:1')).toBe('true')
    expect(dimmed(container, 'file:README.md')).toBe('true')
    expect(dimmed(container, 'step:2')).toBe('false')
    expect(dimmed(container, 'host:ntfy.sh')).toBe('false')
    expect(dimmed(container, 'rule:R1')).toBe('false')
  })

  it('does not dim for a blocked step from the first paint', async () => {
    const { container } = render(<GraphView steps={place([makeStep(1), blocked(2)], 0, { quiet: true })} epoch={0} />)
    await settle()
    expect(dimmed(container, 'step:1')).toBe('false')
  })
})
```
  React Flow puts `data-id` on node wrappers (and on edge wrappers, used in Task 11). Edges only get `data-dim` once `WipeEdge` exists in Task 11, so no edge is asserted here.
- [ ] **Step 6: Rewrite `ui/src/graph/nodes.tsx`.** All colour classes sit in one `STYLE` block so Phase 3 swaps them in one place:

```tsx
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { TIMING, dur, enterDelay } from './choreography'
import { useDimmed } from './dim'
import { HANDLE, type BoxMeta, type FileNode, type HostNode, type RuleNode, type StepNode } from './layout'
import { useMs } from './motionPolicy'
import type { Step, Verdict } from './types'
import { useBoxMotion } from './useBoxMotion'

const HIDDEN_HANDLE = { opacity: 0, width: HANDLE, height: HANDLE } as const
const sec = (n: number): number => n / 1000

// Every colour class lives here; Phase 3 replaces this block with tones.ts.
const STYLE = {
  step: { allowed: 'bg-step border-step text-white', blocked: 'bg-blocked border-step text-white', warned: 'bg-warned border-step text-white' },
  chip: { blocked: 'bg-white text-blocked', warned: 'bg-white text-warned' },
  wipe: { blocked: 'border-rule-edge', warned: 'border-warned' },
  file: 'bg-link text-white',
  fileSecret: 'bg-secret text-ink',
  host: 'bg-link text-white',
  rule: 'border-2 border-rule-edge bg-rule text-white',
  ring: 'border-secret',
  flash: 'bg-white',
}

const VERDICT_UI: Record<Verdict, { tone: string; wipe: string; chip: string | null; chipTone: string }> = {
  allowed: { tone: STYLE.step.allowed, wipe: '', chip: null, chipTone: '' },
  blocked: { tone: STYLE.step.blocked, wipe: STYLE.wipe.blocked, chip: 'BLOCKED', chipTone: STYLE.chip.blocked },
  warned: { tone: STYLE.step.warned, wipe: STYLE.wipe.warned, chip: 'WARN', chipTone: STYLE.chip.warned },
}

function stepDetail(step: Step): string {
  if (step.kind === 'read' || step.kind === 'edit') return step.file ?? ''
  return step.command ?? step.tool ?? ''
}

/** RTL + bdi so a long path truncates on the left and keeps the basename visible. */
function TruncatedPath({ path }: { path: string }) {
  return (
    <span dir="rtl" className="min-w-0 flex-1 truncate text-left font-mono">
      <bdi>{path}</bdi>
    </span>
  )
}

export function StepBox({ id, data }: NodeProps<StepNode>) {
  const { step } = data
  const ms = useMs()
  const dimmed = useDimmed(id)
  const delay = enterDelay(step)
  const detail = stepDetail(step)
  const pathKind = step.kind === 'read' || step.kind === 'edit'
  const { tone, wipe, chip, chipTone } = VERDICT_UI[step.verdict]
  const alarm = step.verdict !== 'allowed'
  return (
    <div
      className="dimmable relative h-full w-full"
      data-dim={dimmed}
      title={`${step.order}: ${step.kind}${detail ? ` ${detail}` : ''}`}
    >
      <Handle id="t" type="target" position={Position.Top} style={HIDDEN_HANDLE} />
      <motion.div
        className={`relative flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 text-base leading-6 ${tone}`}
        initial={step.quiet ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: sec(ms(delay)), duration: sec(ms(dur(TIMING.step))), ease: 'easeOut' }}
      >
        <span className="shrink-0 font-semibold">{step.kind}</span>
        {pathKind ? (
          <TruncatedPath path={detail} />
        ) : (
          <span className="min-w-0 flex-1 truncate font-mono">{detail}</span>
        )}
        {chip !== null && (
          <span className={`shrink-0 rounded px-2 font-bold leading-5 ${chipTone}`}>{chip}</span>
        )}
        {alarm && (
          <motion.div
            aria-hidden
            data-testid="border-wipe"
            className={`pointer-events-none absolute -inset-0.5 rounded-lg border-2 ${wipe}`}
            initial={step.quiet ? false : { clipPath: 'inset(0 100% 0 0)' }}
            animate={{ clipPath: 'inset(0 0% 0 0)' }}
            transition={{
              delay: sec(ms(delay + TIMING.borderWipe.start)),
              duration: sec(ms(dur(TIMING.borderWipe))),
              ease: 'easeOut',
            }}
          />
        )}
      </motion.div>
      <Handle id="b" type="source" position={Position.Bottom} style={HIDDEN_HANDLE} />
      <Handle id="r" type="source" position={Position.Right} style={HIDDEN_HANDLE} />
    </div>
  )
}

interface LaneFrameProps {
  id: string
  meta: BoxMeta
  title: string
  className: string
  /** Rule boxes spring in; file and host boxes fade in. */
  spring?: boolean
  /** A live secret read pulses one ring. */
  ring?: boolean
  children: ReactNode
}

/**
 * Shared frame for file, host and rule boxes. The Handle sits outside the keyed
 * motion element so a re-anchor never remounts it (a remounted handle would
 * drop its edges). Entry runs once per mount; a re-anchor fades in at once.
 */
function LaneFrame({ id, meta, title, className, spring = false, ring = false, children }: LaneFrameProps) {
  const ms = useMs()
  const dimmed = useDimmed(id)
  const { reanchor, bump, tick } = useBoxMotion(meta)
  const { quiet, delay } = meta.enter
  const reduced = ms(1) === 0
  const firstRun = reanchor === 0
  const span = spring ? TIMING.ruleSpring : TIMING.laneBox
  const hidden = spring ? { opacity: 0, scale: 0.6 } : { opacity: 0 }
  const initial = firstRun ? (quiet ? false : hidden) : { opacity: 0 }
  const start = firstRun ? delay + span.start : 0
  const transition =
    spring && firstRun && !reduced
      ? { type: 'spring' as const, duration: sec(dur(span)), bounce: 0.3, delay: sec(start) }
      : {
          duration: sec(ms(firstRun ? dur(span) : dur(TIMING.reanchor))),
          delay: sec(ms(start)),
          ease: 'easeOut' as const,
        }
  return (
    <div className="dimmable relative h-full w-full" data-dim={dimmed} title={title}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <motion.div
        key={`anchor-${reanchor}`}
        className={`relative flex h-full w-full items-center ${className}`}
        initial={initial}
        animate={{ opacity: 1, scale: 1 }}
        transition={transition}
      >
        {children}
        {meta.count >= 2 && (
          <motion.span
            key={`tick-${tick}`}
            className="shrink-0 font-bold tabular-nums"
            initial={tick === 0 ? false : { y: 8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: sec(ms(200)) }}
          >
            x{meta.count}
          </motion.span>
        )}
        {ring && firstRun && !quiet && (
          <motion.div
            aria-hidden
            data-testid="ring"
            className={`pointer-events-none absolute inset-0 rounded border-2 ${STYLE.ring}`}
            initial={{ opacity: 0.9, scale: 1 }}
            animate={{ opacity: 0, scale: 1.25 }}
            transition={{
              delay: sec(ms(delay + TIMING.secretRing.start)),
              duration: sec(ms(dur(TIMING.secretRing))),
              ease: 'easeOut',
            }}
          />
        )}
        {bump > 0 && (
          <motion.div
            key={`bump-${bump}`}
            aria-hidden
            data-testid="bump"
            className={`pointer-events-none absolute inset-0 rounded ${STYLE.flash}`}
            initial={{ opacity: 0.5 }}
            animate={{ opacity: 0 }}
            transition={{ duration: sec(ms(TIMING.brighten.end)) }}
          />
        )}
      </motion.div>
    </div>
  )
}

export function FileBox({ id, data }: NodeProps<FileNode>) {
  const tone = data.sensitive ? STYLE.fileSecret : STYLE.file
  return (
    <LaneFrame
      id={id}
      meta={data}
      title={data.path}
      ring={data.sensitive}
      className={`gap-2 rounded px-2 text-base leading-6 ${tone}`}
    >
      <TruncatedPath path={data.path} />
      {data.sensitive && <span className="shrink-0 font-bold">SECRET</span>}
    </LaneFrame>
  )
}

export function HostBox({ id, data }: NodeProps<HostNode>) {
  return (
    <LaneFrame id={id} meta={data} title={data.host} className={`gap-2 rounded px-2 text-base leading-6 ${STYLE.host}`}>
      <span className="min-w-0 flex-1 truncate font-mono">{data.host}</span>
    </LaneFrame>
  )
}

export function RuleBox({ id, data }: NodeProps<RuleNode>) {
  return (
    <LaneFrame
      id={id}
      meta={data}
      title={`Rule ${data.rule}`}
      spring
      className={`justify-center gap-2 rounded-full px-2 text-base font-bold leading-5 ${STYLE.rule}`}
    >
      <span className="truncate">{data.rule}</span>
    </LaneFrame>
  )
}
```
- [ ] **Step 7: Provide the dim in `GraphView.tsx`.** Add imports `import { DimContext, useBlockDim } from './dim'` and replace the exported `GraphView`:

```tsx
export function GraphView({ steps, epoch }: Props) {
  const ms = useMs()
  const dim = useBlockDim(steps, epoch, ms)
  return (
    <DimContext.Provider value={dim}>
      <ReactFlowProvider key={epoch}>
        <Drawing steps={steps} />
      </ReactFlowProvider>
    </DimContext.Provider>
  )
}
```
- [ ] **Step 8: Add the dim CSS** to `ui/src/index.css` (Phase 3 rewrites the file but keeps this block):

```css
.dimmable {
  transition: opacity 300ms ease;
}
.dimmable[data-dim='true'] {
  opacity: 0.4;
  transition-duration: 150ms;
}
@media (prefers-reduced-motion: reduce) {
  .dimmable,
  .dimmable[data-dim='true'] {
    transition: none;
  }
}
```
- [ ] **Step 9: Run.** `npm --prefix ui run check`. Expected: PASS. If an existing test looked up `title` on the inner element or counted `.react-flow__node` children, adjust to the new outer `div`. A `motion` import problem means Task 7 is incomplete.
- [ ] **Step 10: Commit.** `git add -A ui/src && git commit -m "AG-29: animate step and lane boxes, with counts, brighten and the block dim"`

### Task 11: Edge draw-in (mask wipe)

**Files:**
- Create: `ui/src/graph/WipeEdge.tsx`, `ui/src/graph/WipeEdge.test.tsx`
- Modify: `ui/src/graph/layout.ts`, `ui/src/graph/layout.test.ts`, `ui/src/graph/GraphView.tsx`

**Interfaces:**
- Produces: `WipeData { shape: 'straight' | 'bezier'; quiet: boolean; start: number; end: number }` (absolute ms from the poll's arrival); every edge has `type: 'wipe'`; `WipeEdge`.

- [ ] **Step 1: Layout tests.** Append to `layout.test.ts`:

```ts
describe('edge draw-in data', () => {
  it('gives every edge the wipe type and timing from the table plus the step delay', () => {
    const steps = place(
      [makeStep(1), makeStep(2, { host: 'h', rule: 'R1', verdict: 'blocked', file: 'f' })],
      0,
      { slot: 1, of: 3 },
    )
    const layout = layoutPlaced(steps)
    for (const e of layout.edges) expect(e.type, e.id).toBe('wipe')
    const data = (id: string) => edge(layout, id).data as unknown as { shape: string; quiet: boolean; start: number; end: number }
    expect(data('chain:1:2')).toEqual({ shape: 'straight', quiet: false, start: 80 + 150, end: 80 + 350 })
    expect(data('file-edge:2')).toMatchObject({ shape: 'bezier', start: 80 + 250, end: 80 + 450 })
    expect(data('host-edge:2')).toMatchObject({ start: 80 + 250, end: 80 + 550 })
    expect(data('rule-edge:2')).toMatchObject({ start: 80 + 250, end: 80 + 550 })
  })

  it('marks edges from a quiet step quiet', () => {
    const layout = layoutPlaced(place([makeStep(1), makeStep(2, { file: 'f' })], 0, { quiet: true }))
    for (const e of layout.edges) expect((e.data as unknown as { quiet: boolean }).quiet).toBe(true)
  })
})
```
  Also, in the existing test `joins adjacent drawn steps` nothing changes. Run: expected FAIL.
- [ ] **Step 2: Edit `layout.ts`.** Import `TIMING, type Span` from `./choreography`. Add:

```ts
/** Per-edge data for the first-run draw-in. `start` and `end` are ms from the poll's arrival. */
export interface WipeData extends Record<string, unknown> {
  shape: 'straight' | 'bezier'
  quiet: boolean
  start: number
  end: number
}

function wipe(step: PlacedStep, shape: WipeData['shape'], span: Span): WipeData {
  const delay = enterDelay(step)
  return { shape, quiet: step.quiet, start: delay + span.start, end: delay + span.end }
}
```
  Change `link()` to `link(id, from, to, style, colorKey, zIndex: number | undefined, span: Span)` (a required parameter cannot follow the old optional `zIndex?`, TS1016), and return `{ ..., type: 'wipe', data: wipe(from, 'bezier', span) }`. The chain edge becomes `type: 'wipe', data: wipe(step, 'straight', TIMING.chain)` (replacing `type: 'straight'`). The call sites pass: file edge `undefined` for `zIndex` and `TIMING.edge`; host edge `blocked ? TIMING.blockEdge : TIMING.edge`; rule edge `TIMING.blockEdge`. Run the layout tests → PASS.
- [ ] **Step 3: `WipeEdge` tests.** Create `WipeEdge.test.tsx`:

```tsx
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { GraphView } from './GraphView'
import { MOCK_STEPS } from './mock'
import { makeStep, place } from './testing'

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

afterEach(cleanup)

const masks = (container: HTMLElement) => container.querySelectorAll('mask')

describe('WipeEdge', () => {
  it('masks a fresh edge on its first run with an explicit user-space region', async () => {
    const { container } = render(<GraphView steps={place(MOCK_STEPS)} epoch={0} />)
    await settle()
    expect(masks(container).length).toBeGreaterThan(0)
    for (const mask of masks(container)) {
      expect(mask.getAttribute('maskUnits')).toBe('userSpaceOnUse')
      expect(mask.getAttribute('width')).not.toBeNull()
      expect(mask.getAttribute('height')).not.toBeNull()
    }
  })

  it('removes every mask when the wipe ends, and never brings one back on a later poll', async () => {
    const steps = place(MOCK_STEPS)
    const { container, rerender } = render(<GraphView steps={steps} epoch={0} />)
    await waitFor(() => expect(masks(container).length).toBe(0), { timeout: 4000 })
    rerender(<GraphView steps={steps.map((s) => ({ ...s }))} epoch={0} />)
    await settle()
    expect(masks(container).length).toBe(0)
    expect(container.querySelectorAll('.react-flow__edge').length).toBeGreaterThan(0)
  })

  it('draws a first-paint (quiet) edge with no mask at any time', async () => {
    const { container } = render(<GraphView steps={place(MOCK_STEPS, 0, { quiet: true })} epoch={0} />)
    expect(masks(container).length).toBe(0)
    await settle()
    expect(masks(container).length).toBe(0)
    expect(container.querySelectorAll('.react-flow__edge').length).toBeGreaterThan(0)
  })

  it('dims edges with the same hot set as boxes while a block plays', async () => {
    const steps = place([
      makeStep(1, { kind: 'read', file: 'README.md', command: null }),
      makeStep(2, { verdict: 'blocked', host: 'ntfy.sh', rule: 'R1', command: 'curl x' }),
    ])
    const { container } = render(<GraphView steps={steps} epoch={0} />)
    await settle()
    const dimmed = (id: string) => container.querySelector(`[data-id="${id}"] [data-dim]`)?.getAttribute('data-dim')
    expect(dimmed('chain:1:2')).toBe('true')
    expect(dimmed('file-edge:1')).toBe('true')
    expect(dimmed('host-edge:2')).toBe('false')
    expect(dimmed('rule-edge:2')).toBe('false')
  })

  it('draws no mask under reduced motion', async () => {
    globalThis.setReducedMotion(true)
    const { container } = render(<GraphView steps={place(MOCK_STEPS)} epoch={0} />)
    await settle()
    expect(masks(container).length).toBe(0)
  })
})
```
- [ ] **Step 4: Create `WipeEdge.tsx`:**

```tsx
import { BaseEdge, getBezierPath, getStraightPath, type Edge, type EdgeProps } from '@xyflow/react'
import { motion } from 'motion/react'
import { useState } from 'react'
import { useDimmed } from './dim'
import type { WipeData } from './layout'
import { useMs } from './motionPolicy'

const PAD = 12

export type WipeEdgeType = Edge<WipeData, 'wipe'>

/**
 * An edge that draws in once, on its first run, with an SVG mask: a rect in
 * user space that grows from the source along the dominant axis (all edges in
 * this layout run left to right or top to bottom). A mask works for solid and
 * dashed edges alike and also reveals the arrowhead. The mask is removed when
 * the wipe ends, so settled edges are plain paths. Whether it has played is
 * state, not an effect: StrictMode runs effects twice.
 */
export function WipeEdge(props: EdgeProps<WipeEdgeType>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data } = props
  const ms = useMs()
  const dimmed = useDimmed(id)
  const quiet = data?.quiet ?? true
  const [wiping, setWiping] = useState(() => !quiet && ms(1) > 0)

  const [path] =
    data?.shape === 'straight'
      ? getStraightPath({ sourceX, sourceY, targetX, targetY })
      : getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })

  const x = Math.min(sourceX, targetX) - PAD
  const y = Math.min(sourceY, targetY) - PAD
  const width = Math.abs(targetX - sourceX) + 2 * PAD
  const height = Math.abs(targetY - sourceY) + 2 * PAD
  const horizontal = Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
  const maskId = `wipe-${id}`
  const start = data?.start ?? 0
  const transition = {
    delay: ms(start) / 1000,
    duration: ms((data?.end ?? 0) - start) / 1000,
    ease: 'easeOut' as const,
  }

  return (
    <g className="dimmable" data-dim={dimmed}>
      {wiping && (
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" x={x} y={y} width={width} height={height}>
            {horizontal ? (
              <motion.rect
                x={x}
                y={y}
                height={height}
                fill="white"
                initial={{ width: 0 }}
                animate={{ width }}
                transition={transition}
                onAnimationComplete={() => setWiping(false)}
              />
            ) : (
              <motion.rect
                x={x}
                y={y}
                width={width}
                fill="white"
                initial={{ height: 0 }}
                animate={{ height }}
                transition={transition}
                onAnimationComplete={() => setWiping(false)}
              />
            )}
          </mask>
        </defs>
      )}
      <g mask={wiping ? `url(#${maskId})` : undefined}>
        <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      </g>
    </g>
  )
}
```
  Notes: in `motion`, SVG `x`/`y` behave as CSS transforms, so only `width`/`height` are animated. Edge cases the manual check covers: the arrowhead reveals with the line; an edge whose first render happens before its handles are measured.
- [ ] **Step 5: Register it.** In `GraphView.tsx` add `import { WipeEdge } from './WipeEdge'` and, next to `nodeTypes`, `const edgeTypes = { wipe: WipeEdge }` (module level: a new object each render would replay every wipe), then pass `edgeTypes={edgeTypes}` to `<ReactFlow>`.
- [ ] **Step 6: Run.** `npm --prefix ui run check`. Fix the existing edge-count tests only if they relied on `type: 'straight'`.
- [ ] **Step 7: Commit.** `git add -A ui/src && git commit -m "AG-29: draw edges in once with an SVG mask wipe"`

### Task 12: SECRET SEEN chip and the OFFLINE banner

**Files:** Modify `ui/src/App.tsx`, `ui/src/App.test.tsx`

- [ ] **Step 1: Add tests** to `App.test.tsx` (inside `describe('App', ...)`; `respond`, `advance`, `stepsFrom` are already imported):

```tsx
  const secret = (order: number): Step => ({
    order, kind: 'read', verdict: 'allowed', tool: null, file: '.env', sensitive: true, command: null, host: null, rule: null,
  })

  it('shows SECRET SEEN after a secret read, keeps it, and clears it on New session', async () => {
    let steps: Step[] = stepsFrom(40000, 2)
    vi.stubGlobal('fetch', vi.fn(async () => respond('s', steps)))
    render(<App />)
    await advance(0)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
    steps = [...steps, secret(40002)]
    await advance(1000)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    steps = [...steps, ...stepsFrom(40003, 25)]
    await advance(1000)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await advance(0)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
  })

  it('clears SECRET SEEN when a different session arrives', async () => {
    let body = { session: 's', steps: [secret(40000)] }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => body }) as Response))
    render(<App />)
    await advance(0)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    body = { session: 't', steps: stepsFrom(1, 2) }
    await advance(1000)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
  })

  it('shows SECRET SEEN at once for a secret in the very first response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond('s', [secret(40000)])))
    render(<App />)
    await advance(0)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
  })
```
  Run: FAIL.
- [ ] **Step 2: Rewrite `App.tsx`:**

```tsx
import { motion } from 'motion/react'
import { TIMING, dur } from './graph/choreography'
import { GraphView } from './graph/GraphView'
import { useMs } from './graph/motionPolicy'
import { useRecorder } from './graph/useRecorder'

function App() {
  const mock = new URLSearchParams(window.location.search).get('mock') === '1'
  const { steps, epoch, secretSeen, offline, newSession } = useRecorder(mock)
  const ms = useMs()

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-canvas text-base text-ink">
      <GraphView steps={steps} epoch={epoch} />
      {steps.length === 0 && (
        <p className="pointer-events-none absolute inset-0 grid place-items-center text-base text-muted">
          Waiting for agent actions…
        </p>
      )}
      {offline && (
        <motion.div
          role="alert"
          className="absolute inset-x-0 top-0 z-20 bg-blocked px-4 py-2 pl-80 text-center text-base font-bold text-white"
          initial={{ y: '-100%' }}
          animate={{ y: 0 }}
          transition={{ duration: ms(dur(TIMING.banner)) / 1000, ease: 'easeOut' }}
        >
          OFFLINE - recorder not reachable
        </motion.div>
      )}
      <button
        type="button"
        onClick={newSession}
        className="absolute left-4 top-2 z-30 rounded border-2 border-ink bg-white px-3 text-base leading-6 font-semibold text-ink"
      >
        New session
      </button>
      {secretSeen !== null && (
        <motion.span
          role="status"
          className="absolute left-48 top-2 z-30 rounded bg-secret px-3 text-base leading-6 font-bold text-ink"
          initial={secretSeen.quiet ? false : { opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{
            delay: ms(TIMING.chip.start) / 1000,
            duration: ms(dur(TIMING.chip)) / 1000,
          }}
        >
          SECRET SEEN
        </motion.span>
      )}
    </main>
  )
}

export default App
```
  (The banner's `pl-80` keeps its text clear of the button and the chip.)
- [ ] **Step 3: Run** `npm --prefix ui run check` → PASS. The existing OFFLINE test still finds `role="alert"` and its exact text.
- [ ] **Step 4: Commit.** `git add ui/src/App.tsx ui/src/App.test.tsx && git commit -m "AG-29: add the SECRET SEEN chip and drop the OFFLINE banner in"`

### Task 13: Long mock, burst option, Phase 2 close

**Files:** Modify `ui/src/graph/mock.ts`, `ui/src/graph/useRecorder.ts`, `ui/src/graph/useRecorder.test.tsx`, `ui/src/App.tsx`, `ui/src/App.test.tsx`, `ui/README.md`, `ui/dist/*`

**Interfaces:** Produces `MOCK_SESSION` (34 steps, orders 40,000-40,033, starts with `MOCK_STEPS`), `parseBurst(raw: string | null): number` (1 to 10, else 1), `useRecorder(mock, burst = 1)`.

- [ ] **Step 1: Tests.** Create `ui/src/graph/mock.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { MOCK_SESSION, MOCK_STEPS, parseBurst } from './mock'

describe('MOCK_SESSION', () => {
  it('is about 34 steps from order 40,000, starting with the demo story', () => {
    expect(MOCK_SESSION).toHaveLength(34)
    expect(MOCK_SESSION.slice(0, 5)).toEqual(MOCK_STEPS)
    expect(MOCK_SESSION.map((s) => s.order)).toEqual(Array.from({ length: 34 }, (_, i) => 40000 + i))
  })

  it('exercises shared boxes, a secret, two blocks on one rule and a warned step', () => {
    const count = (f: (s: (typeof MOCK_SESSION)[number]) => boolean) => MOCK_SESSION.filter(f).length
    expect(count((s) => s.file === 'README.md')).toBeGreaterThanOrEqual(3)
    expect(count((s) => s.sensitive)).toBeGreaterThanOrEqual(2)
    expect(count((s) => s.verdict === 'blocked' && s.rule === 'R1')).toBe(2)
    expect(count((s) => s.verdict === 'warned')).toBe(1)
  })
})

describe('parseBurst', () => {
  it.each([
    ['5', 5], ['10', 10], ['1', 1], [null, 1], ['0', 1], ['11', 1], ['x', 1], ['2.5', 1], ['-3', 1],
  ])('%s gives %i', (raw, expected) => {
    expect(parseBurst(raw)).toBe(expected)
  })
})
```
  Update `useRecorder.test.tsx` mock block: replace its `MOCK_STEPS` import with `MOCK_SESSION` (nothing else in the file uses `MOCK_STEPS`, and `tsc -b` rejects an unused import) and import `WINDOW_SIZE` from `./window`; in `replays the scenario one step per 1.5 s...` change the loop to `for (let n = 2; n <= MOCK_SESSION.length; n++) { await advance(MOCK_INTERVAL_MS); expect(result.current.steps).toHaveLength(Math.min(n, WINDOW_SIZE)) }`, the final `toHaveLength` to `WINDOW_SIZE`, and add `expect(result.current.steps.at(-1)?.order).toBe(40033)`. Add:

```tsx
  it('emits `burst` steps per tick', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true, 10))
    expect(result.current.steps).toHaveLength(10)
    await advance(MOCK_INTERVAL_MS)
    expect(result.current.steps).toHaveLength(20)
  })

  it('ignores burst in real mode', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false, 10))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
  })
```
  In `App.test.tsx` add a test that `/?burst=5` (no `mock=1`) still calls `/api/steps` (real mode).
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Extend `mock.ts`.** Keep `MOCK_STEPS` (the 5-step demo story; layout and other tests use it). Add:

```ts
const base = { tool: null, file: null, sensitive: false, command: null, host: null, rule: null }
const step = (order: number, over: Partial<Step>): Step => ({ order, kind: 'shell', verdict: 'allowed', ...base, ...over })

const FILLER: readonly Partial<Step>[] = [
  { kind: 'read', file: 'src/app.ts' },
  { kind: 'edit', file: 'src/app.ts' },
  { kind: 'shell', command: 'npm test' },
  { kind: 'read', file: 'README.md' },
  { kind: 'tool', tool: 'search' },
]

/** What mock mode replays: the demo story, then enough steps to slide the window and reuse boxes. */
export const MOCK_SESSION: readonly Step[] = [
  ...MOCK_STEPS,
  ...Array.from({ length: 24 }, (_, i) => step(40005 + i, FILLER[i % FILLER.length])),
  step(40029, { verdict: 'warned', command: 'rm -rf <arg>', rule: 'R2' }),
  step(40030, { verdict: 'blocked', command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' }),
  step(40031, { kind: 'read', file: '.env', sensitive: true }),
  step(40032, { command: 'ls' }),
  step(40033, { kind: 'read', file: 'README.md' }),
]

/** `?burst=N` makes mock mode emit N steps per tick; anything else means 1. */
export function parseBurst(raw: string | null): number {
  const n = Number(raw)
  return raw !== null && Number.isInteger(n) && n >= 1 && n <= 10 ? n : 1
}
```
  (add `import type { Step } from './types'` if the file lacks it; it already imports `Step`.)
- [ ] **Step 4: Edit `useRecorder.ts`.** Import `MOCK_SESSION`; signature `useRecorder(mock: boolean, burst = 1)`; in the mock effect replace the tick body:

```ts
    function tick(): void {
      shown = Math.min(shown + burst, MOCK_SESSION.length)
      dispatch({ type: 'snapshot', session, steps: MOCK_SESSION.slice(0, shown) })
      if (shown >= MOCK_SESSION.length) clearInterval(timer)
    }
```
  and add `burst` to that effect's dependency array. Update the doc comment ("replays MOCK_SESSION").
- [ ] **Step 5: Edit `App.tsx`.** `import { parseBurst } from './graph/mock'`; compute `const params = new URLSearchParams(window.location.search); const mock = params.get('mock') === '1'; const burst = mock ? parseBurst(params.get('burst')) : 1` and call `useRecorder(mock, burst)`.
- [ ] **Step 6: README.** In `ui/README.md`, after the `/v2/?mock=1` sentence add: "The mock replays a 34-step session (enough to slide the 20-step window); `?mock=1&burst=10` emits 10 steps per tick to check bursts."
- [ ] **Step 7: Run.** `npm --prefix ui run check` → PASS.
- [ ] **Step 8: Phase 2 close.** `npm --prefix ui run build`; the three checks from Global Constraints (stale-build after committing). Manual checks in Chrome: `/v2/?mock=1` at 1.5 s per step then `&burst=10`: no stutter, no console errors; a block plays border wipe, dashed edges, rule spring and a 1.5 s dim, then restores; a secret read rings once and shows SECRET SEEN; repeated README read brightens and ticks `x2`/`x3`; arrowheads reveal with their line; a full run with the OS "reduce motion" setting on (static red border, instant dim, no slide, no wipe); no new request leaves localhost with wifi off (Network panel).
- [ ] **Step 9: Commit.**

```bash
git add -A ui
git commit -m "AG-29: long mock session with burst option; rebuilt ui/dist for phase 2"
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo stale-build-ok
```

---

# Phase 3: theme

### Task 14: Dark theme from one tone table

**Files:**
- Create: `ui/src/graph/tones.ts`, `ui/src/graph/tones.test.ts`
- Modify: `ui/src/index.css` (rewrite), `ui/src/graph/layout.ts` (`EDGE_COLOR`), `ui/src/graph/nodes.tsx` (the `STYLE` block), `ui/src/App.tsx`, `ui/src/graph/GraphView.tsx` (Follow pill classes)

**Interfaces:** Produces `TONES` (`{ bg, text, border, classes }` per variant, token names), `DECOR`, `CSS_ONLY_PAIRS`.

- [ ] **Step 1: Write `tones.test.ts`:**

```ts
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { EDGE_COLOR } from './layout'
import { CSS_ONLY_PAIRS, DECOR, TONES } from './tones'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, '../index.css'), 'utf8')

function token(name: string): string {
  const match = new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css)
  if (match === null) throw new Error(`no token --color-${name} in index.css`)
  return match[1].toLowerCase()
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255).map((v) =>
    v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('contrast helper', () => {
  it('matches known values', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21)
    expect(contrast('#e6edf3', '#0e1116')).toBeCloseTo(16, 0)
  })
})

describe('text pairs', () => {
  it.each(Object.entries(TONES))('%s: text is at least 7:1 on its background', (_name, tone) => {
    expect(contrast(token(tone.text), token(tone.bg))).toBeGreaterThanOrEqual(7)
  })

  it.each(CSS_ONLY_PAIRS)('css-only pair %j is at least 7:1', ({ bg, text }) => {
    expect(contrast(token(text), token(bg))).toBeGreaterThanOrEqual(7)
  })

  it('keeps muted text off the tinted fills', () => {
    for (const [name, tone] of Object.entries(TONES)) {
      if (tone.text === 'muted') expect(['canvas', 'surface'], name).toContain(tone.bg)
    }
  })

  it('has classes that name exactly the tokens in the table', () => {
    for (const [name, tone] of Object.entries(TONES)) {
      const expected = [`bg-${tone.bg}`, `text-${tone.text}`, ...(tone.border === null ? [] : [`border-${tone.border}`])]
      expect(tone.classes.split(/\s+/).sort(), name).toEqual(expected.sort())
    }
  })
})

describe('non-text contrast', () => {
  it.each(Object.entries(TONES).filter(([, t]) => t.border !== null))('%s border is at least 3:1 on canvas', (_n, tone) => {
    expect(contrast(token(tone.border!), token('canvas'))).toBeGreaterThanOrEqual(3)
  })

  it.each(Object.entries(DECOR).filter(([, d]) => d.token !== null))('decoration %s is at least 3:1 on canvas', (_n, d) => {
    expect(contrast(token(d.token!), token('canvas'))).toBeGreaterThanOrEqual(3)
  })

  it.each(Object.entries(EDGE_COLOR))('edge colour %s is at least 3:1 on canvas', (_n, hex) => {
    expect(contrast(hex, token('canvas'))).toBeGreaterThanOrEqual(3)
  })
})

describe('colour lives in one place', () => {
  const sources = import.meta.glob(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}', '!/src/test-setup.ts', '!/src/graph/tones.ts'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  const COLOUR = /\b(?:bg|text|border|ring|fill|stroke|outline)-(?:canvas|surface|ink|muted|fill-[a-z]+|chip-[a-z]+|chain|aux|secret|blocked|warned|link|white|black|step|rule|rule-edge)\b/g

  it('finds the sources it is meant to scan', () => {
    expect(Object.keys(sources).some((p) => p.endsWith('nodes.tsx'))).toBe(true)
    expect(Object.keys(sources).some((p) => p.endsWith('App.tsx'))).toBe(true)
  })

  it('finds no colour utility class outside tones.ts', () => {
    const offenders = Object.entries(sources).flatMap(([path, text]) => [...text.matchAll(COLOUR)].map((m) => `${path}: ${m[0]}`))
    expect(offenders).toEqual([])
  })

  it('recolours the React Flow attribution link with a passing pair', () => {
    expect(css).toMatch(/\.react-flow__attribution[^}]*a[^}]*var\(--color-muted\)/s)
  })
})
```
- [ ] **Step 2: Run to fail.** `npm --prefix ui test -- src/graph/tones.test.ts`.
- [ ] **Step 3: Create `tones.ts`:**

```ts
/**
 * Every colour pair on the page, as data. Components render only `classes`, so
 * the test can iterate this table: there is nothing to scan for pairings.
 * Values are token names; the hex lives in index.css. Muted text is only for
 * canvas or surface: on the tinted fills it fails 7:1.
 */
export interface Tone {
  bg: string
  text: string
  border: string | null
  classes: string
}

const tone = (bg: string, text: string, border: string | null, classes: string): Tone => ({ bg, text, border, classes })

export const TONES = {
  app: tone('canvas', 'ink', null, 'bg-canvas text-ink'),
  empty: tone('canvas', 'muted', null, 'bg-canvas text-muted'),
  step: tone('fill-step', 'ink', 'aux', 'bg-fill-step text-ink border-aux'),
  // The bright alarm border is drawn by the wipe overlay (DECOR), over this neutral one.
  stepBlocked: tone('fill-blocked', 'ink', 'aux', 'bg-fill-blocked text-ink border-aux'),
  stepWarned: tone('fill-warned', 'ink', 'aux', 'bg-fill-warned text-ink border-aux'),
  file: tone('fill-link', 'ink', null, 'bg-fill-link text-ink'),
  fileSecret: tone('fill-secret', 'canvas', null, 'bg-fill-secret text-canvas'),
  host: tone('fill-link', 'ink', null, 'bg-fill-link text-ink'),
  rule: tone('fill-blocked', 'ink', 'blocked', 'bg-fill-blocked text-ink border-blocked'),
  chipBlocked: tone('chip-blocked', 'canvas', null, 'bg-chip-blocked text-canvas'),
  chipWarned: tone('chip-warned', 'canvas', null, 'bg-chip-warned text-canvas'),
  chipSecret: tone('fill-secret', 'canvas', null, 'bg-fill-secret text-canvas'),
  banner: tone('fill-blocked', 'ink', null, 'bg-fill-blocked text-ink'),
  button: tone('surface', 'ink', 'ink', 'bg-surface text-ink border-ink'),
} as const satisfies Record<string, Tone>

/** Decorations that carry no text: borders, rings, flashes. `token` is checked at 3:1 on canvas. */
export const DECOR = {
  wipeBlocked: { token: 'blocked', classes: 'border-blocked' },
  wipeWarned: { token: 'warned', classes: 'border-warned' },
  ring: { token: 'secret', classes: 'border-secret' },
  flash: { token: null, classes: 'bg-ink' },
} as const

/** Pairs set in CSS, not by a class. */
export const CSS_ONLY_PAIRS = [{ name: 'attribution', bg: 'canvas', text: 'muted' }] as const
```
- [ ] **Step 4: Rewrite `ui/src/index.css`** (keeping `@source not '../dist'`, the `.fade-top` block from Task 3 and the `.dimmable` block from Task 10):

```css
@import 'tailwindcss';
@source not '../dist';

@theme static {
  --color-canvas: #0e1116;
  --color-surface: #161b22;
  --color-ink: #e6edf3;
  /* Muted text is for canvas and surface only; it fails 7:1 on the tinted fills. */
  --color-muted: #a8b3c5;

  /* Dark-tinted fills (Look B). */
  --color-fill-step: #374151;
  --color-fill-link: #1e3a8a;
  --color-fill-blocked: #7f1d1d;
  --color-fill-warned: #4c1d95;
  --color-fill-secret: #f59e0b;
  --color-chip-blocked: #fecaca;
  --color-chip-warned: #ddd6fe;

  /* Bright strokes: edges, borders, markers. chain/aux/secret/blocked/warned mirror EDGE_COLOR in layout.ts. */
  --color-chain: #6b7280;
  --color-aux: #9aa3b2;
  --color-secret: #d97706;
  --color-blocked: #ef4444;
  --color-warned: #a78bfa;
  --color-link: #60a5fa;
}

html,
body {
  margin: 0;
  overflow: hidden;
  height: 100%;
  background: var(--color-canvas);
  font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
}

.fade-top {
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 96px);
  mask-image: linear-gradient(to bottom, transparent 0, #000 96px);
}

.dimmable {
  transition: opacity 300ms ease;
}
.dimmable[data-dim='true'] {
  opacity: 0.4;
  transition-duration: 150ms;
}
@media (prefers-reduced-motion: reduce) {
  .dimmable,
  .dimmable[data-dim='true'] {
    transition: none;
  }
}

/* React Flow's attribution link: recoloured to pass 7:1 on the canvas. */
.react-flow__attribution {
  background: transparent;
}
.react-flow__attribution a {
  color: var(--color-muted);
}
```
- [ ] **Step 5: Update `EDGE_COLOR`** in `layout.ts` to match the tokens: `blocked: '#ef4444'`, `warned: '#a78bfa'` (others unchanged: `chain '#6b7280'`, `aux '#9aa3b2'`, `secret '#d97706'`). The existing sync test in `layout.test.ts` compares them with `index.css`.
- [ ] **Step 6: Point the components at `TONES` / `DECOR`.**
  - In `nodes.tsx` add `import { DECOR, TONES } from './tones'` and replace the whole `STYLE` block and `VERDICT_UI` with:

```tsx
const VERDICT_UI: Record<Verdict, { tone: string; wipe: string; chip: string | null; chipTone: string }> = {
  allowed: { tone: TONES.step.classes, wipe: '', chip: null, chipTone: '' },
  blocked: { tone: TONES.stepBlocked.classes, wipe: DECOR.wipeBlocked.classes, chip: 'BLOCKED', chipTone: TONES.chipBlocked.classes },
  warned: { tone: TONES.stepWarned.classes, wipe: DECOR.wipeWarned.classes, chip: 'WARN', chipTone: TONES.chipWarned.classes },
}
```
    Then: the chip span class becomes `shrink-0 rounded px-2 font-bold leading-5 ${chipTone}` (unchanged shape); `STYLE.ring` becomes `DECOR.ring.classes`; `STYLE.flash` becomes `DECOR.flash.classes`; in `FileBox` use `data.sensitive ? TONES.fileSecret.classes : TONES.file.classes`; `HostBox` uses `TONES.host.classes`; `RuleBox` uses `border-2 ${TONES.rule.classes}`.
  - In `App.tsx` import `TONES`: `<main className={\`relative h-dvh w-full overflow-hidden text-base ${TONES.app.classes}\`}>`; the waiting message `... text-base ${TONES.empty.classes}`; the banner `... font-bold ${TONES.banner.classes}`; the "New session" button `... border-2 ${TONES.button.classes}`; the SECRET SEEN chip `... font-bold ${TONES.chipSecret.classes}`.
  - In `GraphView.tsx` the Follow pill: `border-2 ${TONES.button.classes}` (import `TONES`).
  - Remove every other `bg-*`, `text-<token>`, `border-<token>` utility; the colour scan in `tones.test.ts` lists any left.
- [ ] **Step 7: Run.** `npm --prefix ui run check`. Expected: PASS (the `textSize` scan still passes: attribution is in React Flow's own CSS).
- [ ] **Step 8: Commit.** `git add -A ui/src && git commit -m "AG-29: dark theme from one tone table with a 7:1 token test"`

### Task 15: Phase 3 close, docs, final verification

**Files:** Modify `docs/superpowers/specs/2026-10-02-AG-28-draw-graph-design.md` (§ 4), `ui/README.md`, `ui/dist/*`

- [ ] **Step 1: AG-28 spec § 4.** Replace "Colours are CSS variables on `:root`. Light theme only; dark mode goes to AG-31." with "Colours are CSS variables on `:root`. Since AG-29 the page is dark only; every colour pair is in `ui/src/graph/tones.ts`."
- [ ] **Step 2: `ui/README.md`.** Add one sentence to "What the page draws": "The page is dark only. Every colour pair is a row in `src/graph/tones.ts`, and `tones.test.ts` checks each text pair at 7:1 against the tokens in `src/index.css`."
- [ ] **Step 3: Build.** `npm --prefix ui run build`.
- [ ] **Step 4: Final checks.** Run all three commands from Global Constraints (stale-build check after committing). Python is untouched but AGENTS.md says to run the check line before reporting a step done.
- [ ] **Step 5: Manual checks (spec § 11), record results.** In Chrome with the recorder and `fake_agent.py` and also `/v2/?mock=1`:
  - Projector check of the grey, blue and purple fills (they differ by hue only); the red block reads as the loud moment.
  - A long replay (hundreds of steps, e.g. loop `fake_agent.py` or `?mock=1` for several minutes): no coordinate trouble.
  - A real session with step numbers in the tens of thousands: the newest step stays in view for 30 steps in a row; one slide per poll.
  - `.env` with `SECRET` and `x3` stays untruncated in its box; `README.md` too; a 644 px wide window.
  - Wifi off: `/v2/` loads and the Network panel shows only `localhost` requests.
  - The React Flow attribution link is readable and does not touch the newest row.
  - Replay mock at 1.5 s per step: no stutter, no console errors.
- [ ] **Step 6: Commit.**

```bash
git add -A docs ui
git commit -m "AG-29: dark theme docs and rebuilt ui/dist"
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo stale-build-ok
```
- [ ] **Step 7: Report.** Tell the user what works and what does not, with the manual-check results. Then use `superpowers:finishing-a-development-branch`. (The Jira edits for AG-29, AG-31 and AG-28 were already applied on 2026-10-02; nothing is left to write.)
