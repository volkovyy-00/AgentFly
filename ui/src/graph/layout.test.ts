import { MarkerType } from '@xyflow/react'
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CONTENT_W, EDGE_COLOR, FILE_X, HOST_X, LANE_H, ROW_PITCH, STEP_H, STEP_X,
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
