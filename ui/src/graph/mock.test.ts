import { describe, expect, it } from 'vitest'
import { MOCK_SESSION, MOCK_STEPS, parseBurst } from './mock'

describe('MOCK_SESSION', () => {
  it('is about 34 steps from order 40,000, starting with the demo story', () => {
    expect(MOCK_SESSION).toHaveLength(34)
    expect(MOCK_SESSION.slice(0, 5)).toEqual(MOCK_STEPS)
    expect(MOCK_SESSION.map((s) => s.order)).toEqual(Array.from({ length: 34 }, (_, i) => 40000 + i))
  })

  it('exercises shared boxes, a secret, two blocks on one rule and a warned step', () => {
    const count = (f: (s: (typeof MOCK_SESSION)[number]) => boolean) => MOCK_SESSION.filter(f).length
    expect(count((s) => s.file === 'README.md')).toBeGreaterThanOrEqual(3)
    expect(count((s) => s.sensitive)).toBeGreaterThanOrEqual(2)
    expect(count((s) => s.verdict === 'blocked' && s.rule === 'R1')).toBe(2)
    expect(count((s) => s.verdict === 'warned')).toBe(1)
  })
})

describe('parseBurst', () => {
  it.each([
    ['5', 5],
    ['10', 10],
    ['1', 1],
    [null, 1],
    ['0', 1],
    ['11', 1],
    ['x', 1],
    ['2.5', 1],
    ['-3', 1],
  ])('%s gives %i', (raw, expected) => {
    expect(parseBurst(raw)).toBe(expected)
  })
})
