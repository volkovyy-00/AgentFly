import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CARD_PREFS_KEY,
  DEFAULT_PREFS,
  cardBounds,
  defaultCardSize,
  layoutOf,
  readPrefs,
  resolveCardSize,
  writePrefs,
} from './cardPrefs'

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('layoutOf', () => {
  it('stacks below 1080 px and goes side by side from 1080', () => {
    expect(layoutOf(700)).toBe('stacked')
    expect(layoutOf(1079)).toBe('stacked')
    expect(layoutOf(1080)).toBe('side')
  })
})

describe('sizes', () => {
  it('defaults to 46% of the height stacked, and 380 to 480 px of width side by side', () => {
    expect(defaultCardSize('stacked', 750)).toBe(345)
    expect(defaultCardSize('side', 900)).toBe(380)
    expect(defaultCardSize('side', 1400)).toBe(467)
    expect(defaultCardSize('side', 3000)).toBe(480)
  })

  it('keeps the card at least 160 px (280 wide) and leaves the trail 25% and at least 300 px', () => {
    expect(cardBounds('stacked', 750)).toEqual([160, 450])
    expect(cardBounds('stacked', 1600)).toEqual([160, 1200])
    expect(cardBounds('side', 1400)).toEqual([280, 1050])
  })

  it('clamps a remembered size into the bounds of the current pane', () => {
    expect(resolveCardSize('stacked', 750, 700)).toBe(450)
    expect(resolveCardSize('stacked', 750, 50)).toBe(160)
    expect(resolveCardSize('stacked', 750, null)).toBe(345)
  })

  it('has a usable size before the pane is measured', () => {
    expect(resolveCardSize('stacked', 0, null)).toBe(280)
  })
})

describe('remembered state', () => {
  it('round-trips through localStorage', () => {
    writePrefs({ hidden: true, stacked: 300, side: 420 })
    expect(readPrefs()).toEqual({ hidden: true, stacked: 300, side: 420 })
  })

  it('falls back to the defaults for nothing, garbage or bad sizes', () => {
    expect(readPrefs()).toEqual(DEFAULT_PREFS)
    window.localStorage.setItem(CARD_PREFS_KEY, 'not json')
    expect(readPrefs()).toEqual(DEFAULT_PREFS)
    window.localStorage.setItem(CARD_PREFS_KEY, JSON.stringify({ hidden: 'yes', stacked: -4, side: 'wide' }))
    expect(readPrefs()).toEqual(DEFAULT_PREFS)
  })

  it('works without storage: reads fall back, writes do not throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readPrefs()).toEqual(DEFAULT_PREFS)
    expect(() => writePrefs(DEFAULT_PREFS)).not.toThrow()
  })
})
