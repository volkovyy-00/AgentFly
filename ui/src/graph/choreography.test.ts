import { describe, expect, it } from 'vitest'
import {
  DIM_HOLD_MS, EXEMPT, LAST_START_MS, MAX_MS, STAGGER_MAX_MS, TIMING, dur, enterDelay, stagger,
} from './choreography'

describe('timing table', () => {
  it('ends every animation by 800 ms, except the dim hold and its restore', () => {
    for (const [name, span] of Object.entries(TIMING)) {
      if ((EXEMPT as readonly string[]).includes(name)) continue
      expect(span.start, name).toBeGreaterThanOrEqual(0)
      expect(span.end, name).toBeGreaterThan(span.start)
      expect(span.end, name).toBeLessThanOrEqual(MAX_MS)
    }
  })

  it('keeps the dim hold at 1.5 s and exempts only the hold and restore', () => {
    expect(dur(TIMING.dimHold)).toBe(DIM_HOLD_MS)
    expect(DIM_HOLD_MS).toBe(1500)
    expect([...EXEMPT].sort()).toEqual(['dimHold', 'dimOut'])
  })

  it('matches the spec table for the block sequence', () => {
    expect(TIMING.step).toEqual({ start: 0, end: 200 })
    expect(TIMING.borderWipe).toEqual({ start: 100, end: 350 })
    expect(TIMING.blockEdge).toEqual({ start: 250, end: 550 })
    expect(TIMING.ruleSpring).toEqual({ start: 450, end: 800 })
    expect(TIMING.dimIn).toEqual({ start: 0, end: 150 })
  })
})

describe('stagger', () => {
  it('is 0 for the first step and for a lone step (no division by zero)', () => {
    expect(stagger(0, 1)).toBe(0)
    expect(stagger(0, 5)).toBe(0)
    expect(stagger(0, 0)).toBe(0)
    expect(Number.isFinite(stagger(0, 1))).toBe(true)
  })

  it('starts the last step of any burst by 350 ms', () => {
    for (let of = 1; of <= 20; of++) {
      expect(stagger(of - 1, of), `of=${of}`).toBeLessThanOrEqual(LAST_START_MS)
    }
  })

  it('uses 80 ms per step until that would pass 350 ms', () => {
    expect(stagger(1, 3)).toBe(STAGGER_MAX_MS)
    expect(stagger(9, 10)).toBeCloseTo(LAST_START_MS)
  })
})

describe('enterDelay', () => {
  it('is 0 for a quiet step and the stagger otherwise', () => {
    expect(enterDelay({ quiet: true, slot: 2, of: 3 })).toBe(0)
    expect(enterDelay({ quiet: false, slot: 2, of: 3 })).toBe(160)
  })
})
