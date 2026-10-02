import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useMs, useReducedMotion } from './motionPolicy'

describe('motion policy', () => {
  it('passes durations through by default', () => {
    const { result } = renderHook(() => useMs())
    expect(result.current(400)).toBe(400)
    expect(renderHook(() => useReducedMotion()).result.current).toBe(false)
  })

  it('returns 0 for every duration under reduced motion, and reacts to changes', () => {
    const { result } = renderHook(() => useMs())
    act(() => globalThis.setReducedMotion(true))
    expect(result.current(400)).toBe(0)
    expect(result.current(1)).toBe(0)
    act(() => globalThis.setReducedMotion(false))
    expect(result.current(400)).toBe(400)
  })
})
