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
