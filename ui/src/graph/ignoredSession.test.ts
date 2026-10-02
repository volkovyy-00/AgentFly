import { afterEach, describe, expect, it, vi } from 'vitest'
import { IGNORE_KEY, readIgnored, writeIgnored } from './ignoredSession'

afterEach(() => {
  vi.restoreAllMocks()
  window.sessionStorage.clear()
})

describe('ignoredSession', () => {
  it('round-trips under its own key', () => {
    writeIgnored('abc')
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('abc')
    expect(readIgnored()).toBe('abc')
  })

  it('does not share the old page key', () => {
    expect(IGNORE_KEY).not.toBe('fr_ignore_session')
  })

  it('removes the key for null', () => {
    writeIgnored('abc')
    writeIgnored(null)
    expect(readIgnored()).toBeNull()
  })

  it('survives blocked storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readIgnored()).toBeNull()
    expect(() => writeIgnored('abc')).not.toThrow()
  })
})
