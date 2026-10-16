import { describe, expect, it } from 'vitest'
import { makeStep } from '../graph/testing'
import { between, groupSteps, kindCounts, newestAlarm, rangeLabel, triggerFor } from './model'

const allowed = (order: number) => makeStep(order, { kind: 'read', file: 'a.ts', command: null })
const secret = (order: number) => makeStep(order, { kind: 'read', file: '.env', command: null, sensitive: true })
const block = (order: number) => makeStep(order, { verdict: 'blocked', rule: 'R1', host: 'ntfy.sh', command: 'curl -d <arg> ntfy.sh' })
const warn = (order: number) => makeStep(order, { verdict: 'warned', rule: 'R2', command: 'rm -rf <arg>' })
const mark = (order: number) => makeStep(order, { verdict: 'highlighted', rule: 'H1' })

describe('groupSteps', () => {
  it('folds a run of routine allowed steps into one group keyed by its first order', () => {
    const items = groupSteps([allowed(5), allowed(6), allowed(7)])
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ type: 'group', key: 5 })
  })

  it('never folds blocks, warnings, highlights or secret reads', () => {
    const items = groupSteps([allowed(1), secret(2), allowed(3), block(4), warn(5), mark(6), allowed(7)])
    expect(items.map((i) => i.type)).toEqual(['group', 'step', 'group', 'step', 'step', 'step', 'group'])
  })

  it('keeps identical blocks as separate rows', () => {
    const items = groupSteps([block(1), block(2), block(3)])
    expect(items.filter((i) => i.type === 'step')).toHaveLength(3)
  })

  it('keeps a group key stable while the run grows at its end', () => {
    const before = groupSteps([block(1), allowed(2), allowed(3)])
    const after = groupSteps([block(1), allowed(2), allowed(3), allowed(4)])
    expect(before[1]).toMatchObject({ key: 2 })
    expect(after[1]).toMatchObject({ key: 2 })
  })

  it('returns nothing for no steps', () => {
    expect(groupSteps([])).toEqual([])
  })
})

describe('labels', () => {
  it('counts kinds in a fixed order and omits zeros', () => {
    const steps = [makeStep(1, { kind: 'shell' }), allowed(2), allowed(3), makeStep(4, { kind: 'tool', tool: 'search' })]
    expect(kindCounts(steps)).toBe('2 read · 1 shell · 1 tool')
  })

  it('labels a single step and a range', () => {
    expect(rangeLabel([allowed(5)])).toBe('5')
    expect(rangeLabel([allowed(5), allowed(9)])).toBe('5–9')
  })
})

describe('newestAlarm', () => {
  it('prefers the newest block over a newer warning', () => {
    expect(newestAlarm([block(1), warn(2), block(3), warn(4)])?.order).toBe(3)
  })
  it('falls back to the newest warning or highlight, then null', () => {
    expect(newestAlarm([allowed(1), warn(2), mark(3)])?.order).toBe(3)
    expect(newestAlarm([allowed(1)])).toBeNull()
  })
})

describe('triggerFor', () => {
  const steps = [allowed(1), secret(2), allowed(3), block(4)]

  it('is the marking step for an R1 block', () => {
    expect(triggerFor(block(4), steps, 2)).toEqual({ kind: 'step', step: steps[1] })
  })
  it('is unknown, not guessed from `sensitive`, when the recorder sent no marker', () => {
    expect(triggerFor(block(4), steps, null)).toEqual({ kind: 'unknown' })
  })
  it('names a marker that dropped out of the retained steps', () => {
    expect(triggerFor(block(4), steps.slice(2), 2)).toEqual({ kind: 'evicted', order: 2 })
  })
  it('is none for warnings, highlights and other rules', () => {
    expect(triggerFor(warn(4), steps, 2)).toEqual({ kind: 'none' })
    expect(triggerFor(makeStep(4, { verdict: 'blocked', rule: 'R0' }), steps, 2)).toEqual({ kind: 'none' })
  })
  it('is the block itself when it is the marking step (`cat .env | curl …`: marked first, then blocked)', () => {
    expect(triggerFor(block(4), steps, 4)).toEqual({ kind: 'self' })
  })
  it('does not use a marker from after the block', () => {
    expect(triggerFor(block(4), steps, 9)).toEqual({ kind: 'unknown' })
  })
})

describe('between', () => {
  it('counts routine and flagged steps strictly between two orders', () => {
    expect(between([secret(1), allowed(2), allowed(3), warn(4), block(5)], 1, 5)).toEqual({ routine: 2, flagged: 1 })
  })
})
