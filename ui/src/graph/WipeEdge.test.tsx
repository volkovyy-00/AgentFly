import { act, cleanup, render, waitFor } from '@testing-library/react'
import { Position, type EdgeProps } from '@xyflow/react'
import { afterEach, describe, expect, it } from 'vitest'
import { GraphView } from './GraphView'
import { MOCK_STEPS } from './mock'
import { makeStep, place } from './testing'
import { WipeEdge, type WipeEdgeType } from './WipeEdge'

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

  // Its own wait for the wipes allows 4 s, so the test needs more than the 5 s default.
  it('removes every mask when the wipe ends, and never brings one back on a later poll', { timeout: 10_000 }, async () => {
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

  describe('axis and direction', () => {
    type Geometry = Pick<EdgeProps<WipeEdgeType>, 'sourceX' | 'sourceY' | 'targetX' | 'targetY'>
    const edge = (g: Geometry) =>
      (
        <svg>
          <WipeEdge
            {...({
              ...g,
              id: 'e',
              sourcePosition: Position.Right,
              targetPosition: Position.Left,
              data: { shape: 'bezier', quiet: false, start: 0, end: 300 },
            } as unknown as EdgeProps<WipeEdgeType>)}
          />
        </svg>
      )
    const down: Geometry = { sourceX: 100, sourceY: 0, targetX: 110, targetY: 200 }
    const sideways: Geometry = { sourceX: 100, sourceY: 0, targetX: 400, targetY: 20 }
    const growing = (container: HTMLElement) => container.querySelector('mask rect')
    const attrs = (el: Element | null) => [...(el?.attributes ?? [])].map((a) => `${a.name}=${a.value}`)

    it('keeps wiping, with no NaN, when the geometry changes but the axis does not', () => {
      const { container, rerender } = render(edge(down))
      const rect = growing(container)
      expect(rect).not.toBeNull()
      expect(rect?.getAttribute('width')).toBe(String(Math.abs(down.targetX - down.sourceX) + 24))
      rerender(edge({ ...down, targetX: 140, targetY: 260 }))
      expect(growing(container)).toBe(rect)
      expect(attrs(growing(container)).join(' ')).not.toContain('NaN')
      expect(growing(container)?.getAttribute('width')).toBe(String(40 + 24))
    })

    it('ends the wipe and shows the whole edge when a re-anchor turns it mid-wipe', () => {
      const { container, rerender } = render(edge(down))
      expect(growing(container)).not.toBeNull()
      rerender(edge(sideways))
      expect(container.querySelector('mask')).toBeNull()
      expect(container.querySelector('g[mask]')).toBeNull()
      expect(container.querySelector('path')).not.toBeNull()
    })

    it('ends the wipe when a re-anchor flips its direction on the same axis', () => {
      const { container, rerender } = render(edge(down))
      rerender(edge({ ...down, sourceY: 200, targetY: 0 }))
      expect(container.querySelector('mask')).toBeNull()
    })

    it('wipes an edge that runs upward from its source end, not from its arrowhead', () => {
      const flipped = (c: HTMLElement) => c.querySelector('mask g[transform^="rotate(180"]') !== null
      expect(flipped(render(edge(down)).container)).toBe(false)
      cleanup()
      expect(flipped(render(edge({ ...down, sourceY: 200, targetY: 0 })).container)).toBe(true)
      cleanup()
      expect(flipped(render(edge({ ...sideways, sourceX: 400, targetX: 100 })).container)).toBe(true)
    })
  })
})
