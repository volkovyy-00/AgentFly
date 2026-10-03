/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout'
import { longSession, LONG_MARKED_ORDER } from './mock'
import { pickFlagged, windowOfMock } from './mockWindow'
import { makeHidden, makeStep } from './testing'
import type { Hidden, StepKind, Verdict } from './types'
import { WINDOW_SIZE, initialWindowState, windowReducer } from './window'

interface Scenario {
  name: string
  cap: number
  steps: { kind: StepKind; verdict: Verdict; marks?: boolean }[]
  cases: { limit: number; expect: { window: number[]; hidden: Hidden; flagged: number[]; marked_order: number | null } }[]
}

const here = dirname(fileURLToPath(import.meta.url))
const golden = JSON.parse(readFileSync(join(here, '../../../tests/fixtures/window_golden.json'), 'utf8')) as {
  scenarios: Scenario[]
}
const orders = (steps: readonly { order: number }[]) => steps.map((s) => s.order)

describe('windowOfMock matches the Python server on the golden fixture', () => {
  it.each(golden.scenarios.map((s) => [s.name.slice(0, 40), s] as const))('%s', (_name, scenario) => {
    const all = scenario.steps.map((s, i) => makeStep(i + 1, { kind: s.kind, verdict: s.verdict }))
    const marked = scenario.steps.findIndex((s) => s.marks === true)
    const markedOrder = marked === -1 ? null : marked + 1
    for (const c of scenario.cases) {
      const got = windowOfMock(all, c.limit, scenario.cap, markedOrder)
      expect(orders(got.steps), `limit ${c.limit}`).toEqual(c.expect.window)
      expect(got.hidden, `limit ${c.limit}`).toEqual(c.expect.hidden)
      expect(orders(got.flagged), `limit ${c.limit}`).toEqual(c.expect.flagged)
      expect(got.markedOrder, `limit ${c.limit}`).toBe(c.expect.marked_order)
    }
  })
})

describe('windowOfMock', () => {
  it('is empty for no steps', () => {
    expect(windowOfMock([], 20, 500, null)).toEqual({ steps: [], hidden: makeHidden(), flagged: [], markedOrder: null })
  })

  it('counts a step kind it does not know in total only', () => {
    const all = [makeStep(1, { kind: 'weird' as StepKind }), makeStep(2)]
    expect(windowOfMock(all, 1, 500, null).hidden).toEqual(makeHidden({ total: 1 }))
  })

  it('reports no marked order until the marking step has been shown', () => {
    const all = [makeStep(1), makeStep(2)]
    expect(windowOfMock(all, 20, 500, 3).markedOrder).toBeNull()
    expect(windowOfMock([...all, makeStep(3)], 20, 500, 3).markedOrder).toBe(3)
  })
})

describe('pickFlagged', () => {
  it('takes the marking step first, once, then the newest, ascending', () => {
    const blocked = (o: number) => makeStep(o, { verdict: 'blocked' })
    const marking = blocked(3)
    const got = pickFlagged(marking, [blocked(20), blocked(18), marking, blocked(16), blocked(14), blocked(12)], 30)
    expect(orders(got)).toEqual([3, 14, 16, 18, 20])
  })
})

describe('a 500-step session through the reducer and the layout', () => {
  it('draws at most 50 boxes and every flagged step joins the one summary box', () => {
    const all = longSession(500)
    const win = windowOfMock(all, WINDOW_SIZE, 500, LONG_MARKED_ORDER)
    const s = windowReducer(initialWindowState(), {
      type: 'snapshot',
      session: 'long',
      steps: win.steps,
      hidden: win.hidden,
      flagged: win.flagged,
      markedOrder: win.markedOrder,
    })
    expect(win.hidden.total).toBe(480)
    expect(win.flagged.length).toBeLessThanOrEqual(5)
    expect(win.flagged.map((f) => f.order)).toContain(LONG_MARKED_ORDER)
    const layout = layoutGraph(s.steps, s.group, s.markedOrder)
    expect(layout.nodes.length).toBeLessThanOrEqual(50)
    expect(layout.nodes.filter((n) => n.type === 'summary')).toHaveLength(1)
    expect(layout.edges.filter((e) => e.id.startsWith('group-edge'))).toHaveLength(win.flagged.length)
  })

  it('stays within 50 boxes in the worst case: 20 steps, each with its own file, host and rule', () => {
    const steps = Array.from({ length: 20 }, (_, i) =>
      makeStep(1000 + i, { verdict: 'blocked', file: `f${i}`, host: `h${i}.com`, rule: `R${i}`, command: 'x' }),
    )
    const flagged = Array.from({ length: 5 }, (_, i) => makeStep(10 + i, { verdict: 'blocked' }))
    const s = windowReducer(initialWindowState(), {
      type: 'snapshot',
      session: 'w',
      steps,
      hidden: makeHidden({ total: 480, shell: 480, blocked: 30 }),
      flagged,
      markedOrder: null,
    })
    expect(layoutGraph(s.steps, s.group, s.markedOrder).nodes).toHaveLength(20 + 15 + 5 + 1 + 5)
  })
})
