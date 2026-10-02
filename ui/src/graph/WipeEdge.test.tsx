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
