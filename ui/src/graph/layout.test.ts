/// <reference types="node" />
import { MarkerType } from '@xyflow/react'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CONTENT_W, EDGE_COLOR, FILE_X, HOST_X, LANE_H, ROW_PITCH, STEP_H, STEP_X,
  layoutGraph as layoutPlaced, TOP_PAD, hotIds, stepId, fileId, hostId, ruleId, hostEdgeId, ruleEdgeId, chainEdgeId, fileEdgeId, type GraphNode, type Layout,
} from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep, place } from './testing'
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

describe('stability', () => {
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
