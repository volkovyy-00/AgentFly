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

  it('keeps a second block bright from the moment it arrives, even before its own start', () => {
    const first = blocked(0)
    const { result, rerender } = setup({ steps: [first], epoch: 0, ms: same })
    tick(500)
    // The second block is the last of a burst: its own start is later, but it must not mount dimmed.
    rerender({ steps: [first, blocked(1, { slot: 4, of: 5 })], epoch: 0, ms: same })
    expect(result.current.active).toBe(true)
    expect(result.current.hot.has(stepId(101))).toBe(true)
    expect(result.current.hot.has(stepId(100))).toBe(false)
  })

  it('dims a block in the reset poll even when the old session reached far higher rows', () => {
    const { result, rerender } = setup({ steps: [blocked(25)], epoch: 0, ms: same })
    tick(2000)
    rerender({ steps: [blocked(0)], epoch: 1, ms: same })
    tick(0)
    expect(result.current.active).toBe(true)
    expect(result.current.hot.has(stepId(100))).toBe(true)
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
