import { describe, expect, it } from 'vitest'
import { parseSnapshot } from './snapshot'
import { makeHidden } from './testing'

const NO_GROUP = { hidden: null, flagged: [], markedOrder: null }

const good = {
  order: 40000,
  kind: 'shell',
  verdict: 'blocked',
  tool: null,
  file: null,
  sensitive: false,
  command: 'curl -d <arg> ntfy.sh',
  host: 'ntfy.sh',
  rule: 'R1',
}

describe('parseSnapshot', () => {
  it('reads a real body', () => {
    expect(parseSnapshot({ session: 's1', steps: [good] })).toEqual({ session: 's1', steps: [good], ...NO_GROUP })
  })

  it('reads the empty state', () => {
    expect(parseSnapshot({ session: null, steps: [] })).toEqual({ session: null, steps: [], ...NO_GROUP })
  })

  it('rejects a body that is not an object', () => {
    expect(parseSnapshot(null)).toBeNull()
    expect(parseSnapshot('nope')).toBeNull()
    expect(parseSnapshot(42)).toBeNull()
  })

  it('rejects arrays and objects without a steps array (failed poll, keep drawing)', () => {
    expect(parseSnapshot([])).toBeNull()
    expect(parseSnapshot({})).toBeNull()
    expect(parseSnapshot({ session: 's1' })).toBeNull()
    expect(parseSnapshot({ session: 's1', steps: 'nope' })).toBeNull()
  })

  it('accepts an explicit empty steps list', () => {
    expect(parseSnapshot({ session: null, steps: [] })).toEqual({ session: null, steps: [], ...NO_GROUP })
  })

  it('fills missing optional fields with null and sensitive with false', () => {
    const { steps } = parseSnapshot({ session: 's', steps: [{ order: 1, kind: 'read', verdict: 'allowed', file: 'a' }] })!
    expect(steps[0]).toEqual({
      order: 1, kind: 'read', verdict: 'allowed', tool: null, file: 'a', sensitive: false, command: null, host: null, rule: null,
    })
  })

  it('drops malformed steps and keeps the rest', () => {
    const bad = [null, 'x', { kind: 'read', verdict: 'allowed' }, { ...good, order: 'NaN' }, { ...good, kind: 7 }, { ...good, verdict: null }]
    expect(parseSnapshot({ session: 's', steps: [...bad, good] })!.steps).toEqual([good])
  })

  it('keeps a step from a newer server: unknown kind as text, unknown verdict as warned', () => {
    const { steps } = parseSnapshot({ session: 's', steps: [{ ...good, kind: 'mcp', verdict: 'maybe' }] })!
    expect(steps).toHaveLength(1)
    expect(steps[0].kind).toBe('mcp')
    expect(steps[0].verdict).toBe('warned')
  })
})

describe('parseSnapshot: hidden, flagged, marked_order', () => {
  const hidden = makeHidden({ total: 7, shell: 6, read: 1, blocked: 2 })

  it('reads all three fields', () => {
    expect(parseSnapshot({ session: 's', steps: [good], hidden, flagged: [good], marked_order: 3 })).toEqual({
      session: 's',
      steps: [good],
      hidden,
      flagged: [good],
      markedOrder: 3,
    })
  })

  it('treats absent or null fields as no group', () => {
    const body = parseSnapshot({ session: 's', steps: [good], hidden: null, flagged: null, marked_order: null })
    expect(body).toEqual({ session: 's', steps: [good], ...NO_GROUP })
  })

  it.each([
    ['a missing hidden key', { ...hidden, warned: undefined }],
    ['a negative count', { ...hidden, total: -1 }],
    ['a fractional count', { ...hidden, read: 1.5 }],
    ['a string count', { ...hidden, shell: '6' }],
    ['an array', [1, 2, 3]],
    ['a string', 'many'],
  ])('rejects the whole body for hidden with %s', (_name, bad) => {
    expect(parseSnapshot({ session: 's', steps: [good], hidden: bad })).toBeNull()
  })

  it('rejects a flagged that is not an array', () => {
    expect(parseSnapshot({ session: 's', steps: [good], flagged: 'x' })).toBeNull()
  })

  it('drops a bad flagged element like a bad window step', () => {
    const body = parseSnapshot({ session: 's', steps: [good], flagged: [good, { order: 'x' }, 5] })
    expect(body?.flagged).toEqual([good])
  })

  it.each([1.5, '3', true, {}])('rejects marked_order %j', (bad) => {
    expect(parseSnapshot({ session: 's', steps: [good], marked_order: bad })).toBeNull()
  })
})
