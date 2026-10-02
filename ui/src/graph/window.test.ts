import { describe, expect, it } from 'vitest'
import { makeStep, stepsFrom } from './testing'
import { initialWindowState, mergeSteps, windowReducer, type WindowState } from './window'

const orders = (steps: { order: number }[]) => steps.map((s) => s.order)

describe('mergeSteps', () => {
  it('merges overlapping polls by order', () => {
    const merged = mergeSteps(stepsFrom(40000, 10), stepsFrom(40005, 10))
    expect(orders(merged)).toEqual(Array.from({ length: 15 }, (_, i) => 40000 + i))
  })

  it('keeps only the newest 20', () => {
    const merged = mergeSteps(stepsFrom(40000, 20), stepsFrom(40015, 10))
    expect(orders(merged)).toEqual(Array.from({ length: 20 }, (_, i) => 40005 + i))
  })

  it('lets incoming win for the same order', () => {
    const merged = mergeSteps([makeStep(5)], [makeStep(5, { verdict: 'blocked' })])
    expect(merged[0].verdict).toBe('blocked')
  })

  it('keeps the held steps when the poll is empty', () => {
    expect(orders(mergeSteps(stepsFrom(1, 3), []))).toEqual([1, 2, 3])
  })

  it('replaces the window when the server numbering went backwards', () => {
    expect(orders(mergeSteps(stepsFrom(40000, 10), stepsFrom(0, 3)))).toEqual([0, 1, 2])
  })

  it('does not mutate its inputs', () => {
    const held = stepsFrom(1, 3)
    mergeSteps(held, stepsFrom(2, 5))
    expect(orders(held)).toEqual([1, 2, 3])
  })
})

describe('windowReducer', () => {
  const snap = (session: string | null, steps = stepsFrom(40000, 3)) =>
    ({ type: 'snapshot', session, steps }) as const

  it('shows a session and merges later polls', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    s = windowReducer(s, snap('a', stepsFrom(40005, 10)))
    expect(s.session).toBe('a')
    expect(orders(s.steps)).toHaveLength(15)
  })

  it('resets when the session id changes', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    s = windowReducer(s, snap('b', stepsFrom(1, 2)))
    expect(s.session).toBe('b')
    expect(orders(s.steps)).toEqual([1, 2])
  })

  it('returns the same state object when a poll changes nothing', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(windowReducer(s, snap('a'))).toBe(s)
  })

  it('clears on {session: null, steps: []} and keeps the ignored id', () => {
    let s: WindowState = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap(null, []))
    expect(s).toEqual({ session: null, steps: [], ignored: 'a' })
  })

  it('shows nothing for a session with no steps', () => {
    const s = windowReducer(initialWindowState(), snap('a', []))
    expect(s.session).toBeNull()
    expect(s.steps).toEqual([])
  })

  it('newSession hides the shown session and sends nothing', () => {
    const shown = windowReducer(initialWindowState(), snap('a'))
    const s = windowReducer(shown, { type: 'newSession' })
    expect(s).toEqual({ session: null, steps: [], ignored: 'a' })
  })

  it('newSession with nothing shown is a no-op and never stores null', () => {
    const s = initialWindowState()
    expect(windowReducer(s, { type: 'newSession' })).toBe(s)
  })

  it('keeps hiding the ignored session, even when a response arrives late', () => {
    let s = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap('a', stepsFrom(40010, 10)))
    expect(s.steps).toEqual([])
    expect(s.ignored).toBe('a')
  })

  it('a different session id clears the ignored id and shows', () => {
    let s = windowReducer(initialWindowState('a'), snap('a'))
    s = windowReducer(s, snap('b'))
    expect(s.ignored).toBeNull()
    expect(s.session).toBe('b')
    expect(s.steps).toHaveLength(3)
  })

  it('starts hidden when the ignored id was stored by an earlier load', () => {
    const s = windowReducer(initialWindowState('a'), snap('a'))
    expect(s.steps).toEqual([])
  })
})
