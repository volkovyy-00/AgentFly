import { describe, expect, it } from 'vitest'
import { parseSnapshot } from './snapshot'

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
    expect(parseSnapshot({ session: 's1', steps: [good] })).toEqual({ session: 's1', steps: [good] })
  })

  it('reads the empty state', () => {
    expect(parseSnapshot({ session: null, steps: [] })).toEqual({ session: null, steps: [] })
  })

  it('rejects a body that is not an object', () => {
    expect(parseSnapshot(null)).toBeNull()
    expect(parseSnapshot('nope')).toBeNull()
    expect(parseSnapshot(42)).toBeNull()
  })

  it('treats a missing steps array as empty, like the old page', () => {
    expect(parseSnapshot({ session: 's1' })).toEqual({ session: 's1', steps: [] })
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
