import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useMotionPolicy, useMs, useReducedMotion } from './motionPolicy'

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

  it('shares one media query across every reader, and each still sees a change', () => {
    const spy = vi.spyOn(window, 'matchMedia')
    const hooks = Array.from({ length: 5 }, () => renderHook(() => useMotionPolicy()))
    for (const h of hooks) h.rerender()
    expect(spy.mock.calls.length).toBeLessThanOrEqual(1)
    act(() => globalThis.setReducedMotion(true))
    for (const h of hooks) {
      expect(h.result.current.reduced).toBe(true)
      expect(h.result.current.ms(400)).toBe(0)
    }
    spy.mockRestore()
  })
})
