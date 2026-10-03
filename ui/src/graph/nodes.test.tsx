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

  it('does not ring a settled box when its quiet anchor leaves in the same poll as a live read', async () => {
    const { container, rerender } = render(<GraphView steps={place([secretRead(1)], 0, { quiet: true })} epoch={0} />)
    await settle()
    // The quiet first toucher scrolls out and a live read of the same file arrives: moved and touched.
    rerender(<GraphView steps={place([secretRead(2)], 1)} epoch={0} />)
    await settle()
    expect(container.querySelector('[data-testid="ring"]')).toBeNull()
  })
})

describe('re-anchor', () => {
  const read = (order: number) => makeStep(order, { kind: 'read', file: 'f', command: null })
  const fileBox = (container: HTMLElement) => container.querySelector('.react-flow__node-file') as HTMLElement
  const countSpan = (container: HTMLElement) =>
    [...fileBox(container).querySelectorAll('span')].find((s) => /^x\d+$/.test(s.textContent ?? '')) as HTMLElement

  it('does not replay the brighten or the tick when the box re-anchors after a reuse', async () => {
    const { container, rerender } = render(<GraphView steps={place([read(1), read(2)])} epoch={0} />)
    await settle()
    // A reuse: brightens and ticks x2 -> x3.
    rerender(<GraphView steps={place([read(1), read(2), read(3)])} epoch={0} />)
    expect(fileBox(container).querySelector('[data-testid="bump"]')).not.toBeNull()
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400))
    })
    // The first toucher leaves: the box re-anchors, the count falls and no new touch arrives.
    rerender(<GraphView steps={place([read(2), read(3)], 1)} epoch={0} />)
    expect(countSpan(container).textContent).toBe('x2')
    expect(fileBox(container).querySelector('[data-testid="bump"]')).toBeNull()
    expect(countSpan(container).style.transform).toBe('none')
    expect(countSpan(container).style.opacity).toBe('1')
  })

  it('removes the brighten overlay once it has played, and brings it back for the next reuse', async () => {
    const { container, rerender } = render(<GraphView steps={place([read(1), read(2)])} epoch={0} />)
    await settle()
    rerender(<GraphView steps={place([read(1), read(2), read(3)])} epoch={0} />)
    expect(fileBox(container).querySelector('[data-testid="bump"]')).not.toBeNull()
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600))
    })
    expect(fileBox(container).querySelector('[data-testid="bump"]')).toBeNull()
    rerender(<GraphView steps={place([read(1), read(2), read(3), read(4)])} epoch={0} />)
    expect(fileBox(container).querySelector('[data-testid="bump"]')).not.toBeNull()
  })

  it('a re-anchor and a new touch in the same poll still brighten and tick', async () => {
    const { container, rerender } = render(<GraphView steps={place([read(1), read(2)])} epoch={0} />)
    await settle()
    // The first toucher leaves and two new ones arrive: the anchor moves, the newest row advances, the count rises.
    rerender(<GraphView steps={place([read(2), read(3), read(4)], 1)} epoch={0} />)
    expect(countSpan(container).textContent).toBe('x3')
    expect(fileBox(container).querySelector('[data-testid="bump"]')).not.toBeNull()
    expect(countSpan(container).style.transform).toBe('translateY(8px)')
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

  // The wipe's end state: nothing clipped. Its start, 'inset(0 100% 0 0)', hides it all.
  const VISIBLE = 'inset(0 0% 0 0)'
  const wipeClip = (container: HTMLElement) =>
    (container.querySelector('[data-testid="border-wipe"]') as HTMLElement).style.clipPath

  it('wipes the red border in for a live step and ends fully visible', async () => {
    const { container } = render(<GraphView steps={place([blocked(1)])} epoch={0} />)
    expect(wipeClip(container)).toBe('inset(0 100% 0 0)')
    // The wipe ends at 100 + 250 = 350 ms after the step's start.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600))
    })
    expect(wipeClip(container)).toBe(VISIBLE)
  })

  it('shows the full red border for a first-paint step', async () => {
    const { container } = render(<GraphView steps={place([blocked(1)], 0, { quiet: true })} epoch={0} />)
    expect(wipeClip(container)).toBe(VISIBLE)
    await settle()
    expect(wipeClip(container)).toBe(VISIBLE)
  })

  it('shows the full red border under reduced motion, not hidden mid-wipe', async () => {
    globalThis.setReducedMotion(true)
    const { container } = render(<GraphView steps={place([blocked(1)])} epoch={0} />)
    expect(wipeClip(container)).toBe(VISIBLE)
    await settle()
    expect(wipeClip(container)).toBe(VISIBLE)
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
