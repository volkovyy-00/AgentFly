/// <reference types="node" />
import { MarkerType } from '@xyflow/react'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CONTENT_W, EDGE_COLOR, FILE_X, HOST_X, LANE_H, ROW_PITCH, STEP_H, STEP_X,
  layoutGraph as layoutPlaced, TOP_PAD, hotIds, stepId, fileId, hostId, ruleId, hostEdgeId, ruleEdgeId, chainEdgeId, fileEdgeId, type GraphNode, type Layout,
  MAX_LANE_BOXES, MAX_RULE_BOXES, SUMMARY_ID, drawnFlagged, groupEdgeId, groupRows,
} from './layout'
import { MOCK_STEPS } from './mock'
import { makeHidden, makeStep, place, stepsFrom } from './testing'
import type { Step } from './types'

/** Rows 0.. in list order: the old behaviour, for tests that do not care about rows. */
const layoutGraph = (steps: readonly Step[]) => layoutPlaced(place(steps))

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
    expect(layoutGraph([])).toEqual({ nodes: [], edges: [] })
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
    expect(node(layout, 'file:.env').data).toMatchObject({ path: '.env', sensitive: true })
    expect(node(layout, 'file:README.md').data).toMatchObject({ path: 'README.md', sensitive: false })
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

  it('re-anchors a box to the next drawn step that touches it, keeping rows', () => {
    const steps = [makeStep(1, { file: 'f' }), makeStep(2), makeStep(3, { file: 'f' })]
    expect(node(layoutGraph(steps), 'file:f').position.y).toBe(centre(0) - 12)
    const slid = layoutPlaced(place(steps.slice(1), 1))
    expect(node(slid, 'file:f').position.y).toBe(centre(2) - 12)
    expect(node(slid, 'step:3').position.y).toBe(centre(2) - STEP_H / 2)
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
    expect(edge(layout, 'host-edge:1').zIndex).toBe(1)
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

  it('puts a closed arrowhead at the target of every edge, coloured to match the stroke family', () => {
    const strokeToColor: Record<string, string> = {
      'var(--color-chain)': EDGE_COLOR.chain,
      'var(--color-aux)': EDGE_COLOR.aux,
      'var(--color-secret)': EDGE_COLOR.secret,
      'var(--color-blocked)': EDGE_COLOR.blocked,
      'var(--color-warned)': EDGE_COLOR.warned,
    }
    const steps = [
      ...MOCK_STEPS,
      makeStep(40005, { verdict: 'warned', rule: 'R2', host: 'ok.example', command: 'curl ok.example' }),
    ]
    const layout = layoutGraph(steps)
    expect(layout.edges.length).toBeGreaterThan(0)
    for (const e of layout.edges) {
      const stroke = String(e.style?.stroke)
      const color = strokeToColor[stroke]
      expect(color, `${e.id} stroke ${stroke}`).toBeTruthy()
      expect(e.markerEnd).toEqual(
        expect.objectContaining({
          type: MarkerType.ArrowClosed,
          color,
        }),
      )
    }
  })

  it('keeps EDGE_COLOR in sync with the theme hex values in index.css', () => {
    // Discover via the same glob as textSize.test.ts; read bytes from disk because
    // Vite's Tailwind plugin yields an empty string for `index.css?raw`.
    const sources = import.meta.glob(
      ['/src/**/*.{ts,tsx,css}', '!/src/**/*.test.{ts,tsx}', '!/src/test-setup.ts'],
      {
        query: '?raw',
        import: 'default',
        eager: true,
      },
    ) as Record<string, string>
    expect(Object.keys(sources).some((path) => path.endsWith('index.css'))).toBe(true)
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../index.css'), 'utf8')
    for (const [name, hex] of Object.entries(EDGE_COLOR)) {
      expect(css).toMatch(new RegExp(`--color-${name}:\\s*${hex}`))
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

describe('stability: window boxes never move; the group moves with the window (see "the group above the window")', () => {
  const positions = (layout: Layout) => new Map(layout.nodes.map((n) => [n.id, { ...n.position }]))

  it('a pure append moves nothing that was already drawn', () => {
    const before = positions(layoutGraph(busy(12)))
    const after = positions(layoutGraph(busy(13)))
    for (const [id, p] of before) expect(after.get(id), id).toEqual(p)
  })

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
})

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

describe('enter timing on shared boxes', () => {
  it('takes the quiet flag and delay from the anchor step', () => {
    const steps = place([makeStep(1, { file: 'f' }), makeStep(2, { file: 'f' })], 0, { quiet: false, slot: 1, of: 3 })
    const data = node(layoutPlaced(steps), 'file:f').data as unknown as { enter: { quiet: boolean; delay: number } }
    expect(data.enter).toEqual({ quiet: false, delay: 80 })
    const quiet = node(layoutPlaced(place([makeStep(1, { file: 'f' })], 0, { quiet: true })), 'file:f')
    expect((quiet.data as unknown as { enter: { quiet: boolean } }).enter.quiet).toBe(true)
  })
})

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

describe('the group above the window', () => {
  const win = (first = 40100, firstRow = 100) => place(stepsFrom(first, 20), firstRow)
  const blockedAt = (order: number) =>
    makeStep(order, { verdict: 'blocked', rule: 'R1', host: 'ntfy.sh', command: 'curl -d <arg> ntfy.sh' })
  const group = (flagged = [blockedAt(40003), makeStep(40050, { verdict: 'warned', rule: 'R2' })]) => ({
    hidden: makeHidden({ total: 97, shell: 97, blocked: 1, warned: 1 }),
    flagged,
  })

  it('stacks the summary, the flagged steps and then the window, from rows that may be negative', () => {
    const layout = layoutPlaced(win(), group())
    expect(node(layout, SUMMARY_ID).position.y).toBe(centre(97) - STEP_H / 2)
    expect(node(layout, 'step:40003').position.y).toBe(centre(98) - STEP_H / 2)
    expect(node(layout, 'step:40050').position.y).toBe(centre(99) - STEP_H / 2)
    expect(node(layout, 'step:40100').position.y).toBe(centre(100) - STEP_H / 2)
    const early = layoutPlaced(win(40010, 3), group())
    expect(node(early, SUMMARY_ID).position.y).toBe(centre(0) - STEP_H / 2)
    const negative = layoutPlaced(win(40010, 1), group())
    expect(node(negative, SUMMARY_ID).position.y).toBe(centre(-2) - STEP_H / 2)
  })

  it('joins the group in a chain with quiet edges keyed on the target, and not to the window', () => {
    const layout = layoutPlaced(win(), group())
    expect(edge(layout, groupEdgeId(40003))).toMatchObject({ source: SUMMARY_ID, target: 'step:40003', sourceHandle: 'b', targetHandle: 't' })
    expect(edge(layout, groupEdgeId(40050))).toMatchObject({ source: 'step:40003', target: 'step:40050' })
    for (const id of [groupEdgeId(40003), groupEdgeId(40050)]) expect(edge(layout, id).data).toMatchObject({ quiet: true })
    expect(layout.edges.some((e) => e.target === 'step:40100' && e.source !== 'step:40100' && e.id.startsWith('group'))).toBe(false)
    expect(layout.edges.some((e) => e.source === 'step:40050' && e.target === 'step:40100')).toBe(false)
  })

  it('draws a summary alone when nothing is flagged', () => {
    const layout = layoutPlaced(win(), group([]))
    expect(node(layout, SUMMARY_ID).position.y).toBe(centre(99) - STEP_H / 2)
    expect(layout.edges.filter((e) => e.id.startsWith('group-edge'))).toEqual([])
    expect(groupRows(win(), group([]))).toBe(1)
  })

  it('draws no group for none, or for no window', () => {
    expect(has(layoutPlaced(win(), null), SUMMARY_ID)).toBe(false)
    expect(layoutPlaced([], group())).toEqual({ nodes: [], edges: [] })
    expect(groupRows(win(), null)).toBe(0)
  })

  it('gives flagged steps no lane boxes of their own, and they never touch a shared box', () => {
    const flagged = [makeStep(40003, { kind: 'read', file: 'shared.txt', command: null, verdict: 'blocked', rule: 'R1', host: 'x.com' })]
    const steps = win()
    steps[10] = { ...steps[10], kind: 'read', file: 'shared.txt', command: null }
    const layout = layoutPlaced(steps, group(flagged))
    const box = node(layout, 'file:shared.txt')
    expect(box.data).toMatchObject({ count: 1, anchorRow: 110, lastTouchRow: 110 })
    expect(layout.nodes.some((n) => n.id === 'host:x.com' || n.id === 'rule:R1')).toBe(false)
    expect(layout.edges.some((e) => e.id === 'file-edge:40003' || e.id === 'host-edge:40003' || e.id === 'rule-edge:40003')).toBe(false)
  })

  it('never draws a node id twice: the window wins over a flagged step, and a repeated flagged step counts once', () => {
    const inWindow = makeStep(40105, { verdict: 'blocked', rule: 'R1' })
    const layout = layoutPlaced(win(), group([blockedAt(40003), inWindow, blockedAt(40003)]))
    const ids = layout.nodes.map((n) => n.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(drawnFlagged(win(), group([blockedAt(40003), inWindow, blockedAt(40003)])).map((s) => s.order)).toEqual([40003])
    expect(node(layout, 'step:40105').position.y).toBe(centre(105) - STEP_H / 2)
  })

  it('marks the marking step wherever it is drawn', () => {
    const layout = layoutPlaced(win(), group(), 40003)
    expect(node(layout, 'step:40003').data).toMatchObject({ flagged: true, marked: true })
    expect(node(layout, 'step:40050').data).toMatchObject({ flagged: true, marked: false })
    const inWindow = layoutPlaced(win(), group(), 40105)
    expect(node(inWindow, 'step:40105').data).toMatchObject({ flagged: false, marked: true })
    expect(node(inWindow, 'step:40100').data).toMatchObject({ flagged: false, marked: false })
  })

  it('takes no coordinate from order: orders near 1 and near 100,000 lay out the same', () => {
    const shape = (first: number) =>
      layoutPlaced(place(stepsFrom(first, 20), 100), {
        hidden: makeHidden({ total: 5, shell: 5, blocked: 1 }),
        flagged: [makeStep(first - 50, { verdict: 'blocked', rule: 'R1' })],
      }).nodes.map((n) => n.position)
    expect(shape(100_000)).toEqual(shape(60))
  })

  it('moves the whole group down one row when the window slides, with the same ids', () => {
    const before = layoutPlaced(win(40100, 100), group())
    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    const after = layoutPlaced(slid, group())
    for (const id of [SUMMARY_ID, 'step:40003', 'step:40050']) {
      expect(node(after, id).position.y - node(before, id).position.y, id).toBe(ROW_PITCH)
      expect(node(after, id).position.x).toBe(node(before, id).position.x)
    }
    for (const id of ['step:40105', 'step:40119']) expect(node(after, id).position).toEqual(node(before, id).position)
  })

  it('moves nothing in the group when the departing step becomes flagged, and the step keeps its node id and place', () => {
    const departing = blockedAt(40100)
    const before = layoutPlaced(win(40100, 100), group())
    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    const after = layoutPlaced(slid, group([blockedAt(40003), makeStep(40050, { verdict: 'warned', rule: 'R2' }), departing]))
    for (const id of [SUMMARY_ID, 'step:40003', 'step:40050']) expect(node(after, id).position, id).toEqual(node(before, id).position)
    expect(node(after, 'step:40100').position).toEqual(node(before, 'step:40100').position)
    expect(edge(after, groupEdgeId(40100)).source).toBe('step:40050')
  })
})

describe('lane box caps', () => {
  const count = (layout: Layout, type: string) => layout.nodes.filter((n) => n.type === type).length

  it('draws at most 15 file and host boxes, dropping the least recently touched, and their edges with them', () => {
    const steps = place(Array.from({ length: 20 }, (_, i) => makeStep(i + 1, { kind: 'read', file: `f${i}`, command: null })))
    const layout = layoutPlaced(steps)
    expect(count(layout, 'file')).toBe(MAX_LANE_BOXES)
    for (let i = 0; i < 5; i++) {
      expect(has(layout, `file:f${i}`), `f${i}`).toBe(false)
      expect(layout.edges.some((e) => e.id === `file-edge:${i + 1}`)).toBe(false)
      expect(has(layout, `step:${i + 1}`)).toBe(true)
    }
    for (let i = 5; i < 20; i++) expect(has(layout, `file:f${i}`)).toBe(true)
  })

  it('counts files and hosts together, and drops a file before a host on a tie', () => {
    const steps = [
      makeStep(1, { kind: 'read', file: 'a', host: 'h', command: null }),
      ...Array.from({ length: 14 }, (_, i) => makeStep(i + 2, { kind: 'read', file: `f${i}`, command: null })),
    ]
    const layout = layoutPlaced(place(steps))
    expect(count(layout, 'file') + count(layout, 'host')).toBe(MAX_LANE_BOXES)
    expect(has(layout, 'file:a')).toBe(false)
    expect(has(layout, 'host:h')).toBe(true)
  })

  it('draws at most 5 rule boxes', () => {
    const steps = place(Array.from({ length: 8 }, (_, i) => makeStep(i + 1, { verdict: 'blocked', rule: `R${i}`, host: 'x.com' })))
    const layout = layoutPlaced(steps)
    expect(count(layout, 'rule')).toBe(MAX_RULE_BOXES)
    expect(has(layout, 'rule:R0')).toBe(false)
    expect(has(layout, 'rule:R7')).toBe(true)
  })

  it('never brings a box back without a touch as the window slides', () => {
    const stream = Array.from({ length: 70 }, (_, i) =>
      makeStep(i + 1, {
        kind: 'read',
        file: `f${(i * 7 + 3) % 25}`,
        host: i % 3 === 0 ? `h${i % 8}` : null,
        command: null,
      }),
    )
    const lane = (layout: Layout) => new Set(layout.nodes.filter((n) => n.type === 'file' || n.type === 'host').map((n) => n.id))
    let before = lane(layoutPlaced(place(stream.slice(0, 20), 0)))
    for (let start = 1; start <= 50; start++) {
      const newest = stream[start + 19]
      const after = lane(layoutPlaced(place(stream.slice(start, start + 20), start)))
      const touched = new Set([`file:${newest.file}`, ...(newest.host === null ? [] : [`host:${newest.host}`])])
      for (const id of after) expect(before.has(id) || touched.has(id), `${id} returned at ${start}`).toBe(true)
      before = after
    }
  })

  // Guards the tie-break: swapping it for `anchorRow` (which changes when a toucher leaves) fails this
  // test (43 violations over the 300 seeds when tried) while the fixed (kind, id) tie-break passes.
  it('never brings a box back without a touch, over 300 seeded random streams', () => {
    const rng = (seed: number) => {
      let a = seed
      return () => {
        a = (a + 0x6d2b79f5) | 0
        let t = Math.imul(a ^ (a >>> 15), 1 | a)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
      }
    }
    const boxes = (layout: Layout) =>
      new Set(layout.nodes.filter((n) => n.type === 'file' || n.type === 'host' || n.type === 'rule').map((n) => n.id))
    const returned: string[] = []
    for (let seed = 1; seed <= 300; seed++) {
      const next = rng(seed)
      const pick = (n: number) => Math.floor(next() * n)
      const stream = Array.from({ length: 80 }, (_, i) =>
        makeStep(i + 1, {
          kind: 'read',
          file: next() < 0.8 ? `f${pick(25)}` : null,
          host: next() < 0.5 ? `h${pick(10)}` : null,
          rule: next() < 0.3 ? `R${pick(8)}` : null,
          command: null,
        }),
      )
      let before = boxes(layoutPlaced(place(stream.slice(0, 20), 0)))
      for (let start = 1; start <= 60; start++) {
        const newest = stream[start + 19]
        const after = boxes(layoutPlaced(place(stream.slice(start, start + 20), start)))
        const touched = new Set([
          ...(newest.file === null ? [] : [`file:${newest.file}`]),
          ...(newest.host === null ? [] : [`host:${newest.host}`]),
          ...(newest.rule === null ? [] : [`rule:${newest.rule}`]),
        ])
        for (const id of after) if (!before.has(id) && !touched.has(id)) returned.push(`seed ${seed} start ${start}: ${id}`)
        before = after
      }
    }
    expect(returned).toEqual([])
  })
})
