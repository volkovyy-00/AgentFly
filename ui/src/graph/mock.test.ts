import { describe, expect, it } from 'vitest'
import { LONG_MARKED_ORDER, MOCK_MARKED_ORDER, MOCK_SESSION, MOCK_STEPS, longSession, parseBurst, parseLen } from './mock'

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

describe('MOCK_MARKED_ORDER', () => {
  it('names the demo story\'s .env read', () => {
    expect(MOCK_SESSION.find((s) => s.order === MOCK_MARKED_ORDER)).toMatchObject({ file: '.env', sensitive: true })
  })
})

describe('longSession', () => {
  it('is n steps from order 40,000 with a marking read at index 1 and a block about every 13', () => {
    const steps = longSession(500)
    expect(steps).toHaveLength(500)
    expect(steps.map((s) => s.order)).toEqual(Array.from({ length: 500 }, (_, i) => 40000 + i))
    expect(steps.find((s) => s.order === LONG_MARKED_ORDER)).toMatchObject({ file: '.env', sensitive: true })
    expect(steps.filter((s) => s.verdict === 'blocked').length).toBeGreaterThanOrEqual(30)
    expect(steps.filter((s) => s.verdict === 'warned').length).toBeGreaterThanOrEqual(10)
    expect(longSession(3)).toHaveLength(3)
  })
})

describe('parseLen', () => {
  it.each([
    ['500', 500],
    ['1', 1],
    ['2000', 2000],
    [null, null],
    ['0', null],
    ['2001', null],
    ['x', null],
    ['2.5', null],
    ['-3', null],
    ['', null],
  ])('%s gives %s', (raw, expected) => {
    expect(parseLen(raw)).toBe(expected)
  })
})
