import { describe, expect, it } from 'vitest'
import { enterDelay } from './choreography'
import { makeStep, stepsFrom } from './testing'
import { WINDOW_SIZE, initialWindowState, windowReducer, type WindowState } from './window'

const orders = (steps: { order: number }[]) => steps.map((s) => s.order)
const snap = (session: string | null, steps = stepsFrom(40000, 3), first = false) =>
  ({ type: 'snapshot', session, steps, first }) as const

describe('stable rows', () => {
  it('gives rows from 0 in order and keeps them as polls merge', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    s = windowReducer(s, snap('a', stepsFrom(40005, 10)))
    expect(orders(s.steps)).toEqual(Array.from({ length: 15 }, (_, i) => 40000 + i))
    expect(s.steps.map((x) => x.row)).toEqual(Array.from({ length: 15 }, (_, i) => i))
    expect(s.nextRow).toBe(15)
  })

  it('keeps each step on its row while the window slides', () => {
    let s = initialWindowState()
    for (const first of [40000, 40005, 40010, 40015, 40020, 40025, 40030]) {
      s = windowReducer(s, snap('a', stepsFrom(first, 10)))
    }
    expect(s.steps).toHaveLength(WINDOW_SIZE)
    expect(s.steps[0].order).toBe(40020)
    expect(s.steps[0].row).toBe(20)
    expect(s.steps.at(-1)?.row).toBe(39)
  })

  it('sorts incoming steps by order before assigning rows', () => {
    const reversed = [...stepsFrom(40000, 4)].reverse()
    const s = windowReducer(initialWindowState(), snap('a', reversed))
    expect(orders(s.steps)).toEqual([40000, 40001, 40002, 40003])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1, 2, 3])
  })

  it('tags a poll\'s new steps with slot and of', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    s = windowReducer(s, snap('a', stepsFrom(40001, 6)))
    expect(s.steps.map((x) => [x.slot, x.of])).toEqual([[0, 3], [1, 3], [2, 3], [0, 4], [1, 4], [2, 4], [3, 4]])
  })

  it('updates a known step in place and keeps its row', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(5)]))
    s = windowReducer(s, snap('a', [makeStep(5, { verdict: 'blocked' })]))
    expect(s.steps).toHaveLength(1)
    expect(s.steps[0]).toMatchObject({ order: 5, verdict: 'blocked', row: 0 })
  })

  it('ignores an unknown order below the newest held step', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(10), makeStep(12)]))
    s = windowReducer(s, snap('a', [makeStep(11), makeStep(12)]))
    expect(orders(s.steps)).toEqual([10, 12])
  })

  it('resets rows and bumps epoch when the server numbering goes backwards', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 10)))
    const before = s.epoch
    s = windowReducer(s, snap('a', stepsFrom(0, 3)))
    expect(orders(s.steps)).toEqual([0, 1, 2])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1, 2])
    expect(s.epoch).toBe(before + 1)
  })

  it('does not mutate its input', () => {
    const incoming = stepsFrom(1, 3)
    windowReducer(initialWindowState(), snap('a', incoming))
    expect(orders(incoming)).toEqual([1, 2, 3])
  })
})

describe('first response (quiet)', () => {
  it('marks only steps appended with first: true', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3), true))
    expect(s.steps.every((x) => x.quiet)).toBe(true)
    s = windowReducer(s, snap('a', stepsFrom(40000, 5), false))
    expect(s.steps.map((x) => x.quiet)).toEqual([true, true, true, false, false])
  })

  it('never marks anything quiet by default', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(s.steps.every((x) => !x.quiet)).toBe(true)
  })
})

describe('secretSeen', () => {
  const secret = makeStep(40001, { kind: 'read', file: '.env', sensitive: true, command: null })

  it('is set by a sensitive step, stays, and records whether it was quiet', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(40000), secret], true))
    expect(s.secretSeen).toEqual({ quiet: true, delay: 0 })
    s = windowReducer(s, snap('a', stepsFrom(40002, 30)))
    expect(s.secretSeen).toEqual({ quiet: true, delay: 0 })
    const live = windowReducer(initialWindowState(), snap('a', [secret]))
    expect(live.secretSeen).toEqual({ quiet: false, delay: 0 })
  })

  it("carries the secret step's own stagger, so the chip follows its box", () => {
    const burst = [...stepsFrom(39992, 9), { ...secret, order: 40001 }]
    const s = windowReducer(initialWindowState(), snap('a', burst))
    const placed = s.steps.find((x) => x.sensitive)!
    expect(placed.slot).toBe(9)
    expect(s.secretSeen).toEqual({ quiet: false, delay: enterDelay(placed) })
    expect(s.secretSeen!.delay).toBeGreaterThan(0)
  })

  it('starts the chip at once when an already drawn step turns sensitive', () => {
    let s = windowReducer(initialWindowState(), snap('a', [makeStep(40000), makeStep(40001)]))
    s = windowReducer(s, snap('a', [makeStep(40000), secret]))
    expect(s.secretSeen).toEqual({ quiet: false, delay: 0 })
  })

  it('is null until a sensitive step is seen', () => {
    expect(windowReducer(initialWindowState(), snap('a')).secretSeen).toBeNull()
  })

  it('clears on New session and on a different session id', () => {
    let s = windowReducer(initialWindowState(), snap('a', [secret]))
    expect(windowReducer(s, { type: 'newSession' }).secretSeen).toBeNull()
    s = windowReducer(s, snap('b', [makeStep(1)]))
    expect(s.secretSeen).toBeNull()
  })
})

describe('windowReducer sessions', () => {
  it('shows a session and resets when the session id changes, bumping epoch', () => {
    let s = windowReducer(initialWindowState(), snap('a', stepsFrom(40000, 3)))
    const epoch = s.epoch
    s = windowReducer(s, snap('b', stepsFrom(1, 2)))
    expect(s.session).toBe('b')
    expect(orders(s.steps)).toEqual([1, 2])
    expect(s.steps.map((x) => x.row)).toEqual([0, 1])
    expect(s.epoch).toBe(epoch + 1)
  })

  it('starts the first session without a reset: epoch stays put on page load and after New session', () => {
    const initial = initialWindowState()
    const shown = windowReducer(initial, snap('a'))
    expect(shown.epoch).toBe(initial.epoch)
    const cleared = windowReducer(shown, { type: 'newSession' })
    const next = windowReducer(cleared, snap('b', stepsFrom(1, 2)))
    expect(next.session).toBe('b')
    expect(next.epoch).toBe(cleared.epoch)
  })

  it('returns the same state object when a poll changes nothing', () => {
    const s = windowReducer(initialWindowState(), snap('a'))
    expect(windowReducer(s, snap('a'))).toBe(s)
    const full = windowReducer(s, snap('a', stepsFrom(40000, 40)))
    expect(windowReducer(full, snap('a', full.steps.slice(-10)))).toBe(full)
  })

  it('clears on {session: null, steps: []} and keeps the ignored id', () => {
    let s: WindowState = windowReducer(initialWindowState(), snap('a'))
    s = windowReducer(s, { type: 'newSession' })
    s = windowReducer(s, snap(null, []))
    expect(s).toMatchObject({ session: null, steps: [], ignored: 'a', secretSeen: null })
  })

  it('shows nothing for a session with no steps', () => {
    const s = windowReducer(initialWindowState(), snap('a', []))
    expect(s.session).toBeNull()
    expect(s.steps).toEqual([])
  })

  it('newSession hides the shown session, bumps epoch and sends nothing', () => {
    const shown = windowReducer(initialWindowState(), snap('a'))
    const s = windowReducer(shown, { type: 'newSession' })
    expect(s).toMatchObject({ session: null, steps: [], ignored: 'a', epoch: shown.epoch + 1 })
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
