import { renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { describe, expect, it } from 'vitest'
import { useBoxMotion } from './useBoxMotion'

type Meta = { anchorRow: number; lastTouchRow: number; count: number }
const setup = (meta: Meta) => renderHook((m: Meta) => useBoxMotion(m), { initialProps: meta })
const base: Meta = { anchorRow: 5, lastTouchRow: 9, count: 3 }

describe('useBoxMotion', () => {
  it('starts at zero, also under StrictMode', () => {
    expect(setup(base).result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
    const strict = renderHook(() => useBoxMotion(base), { wrapper: StrictMode })
    expect(strict.result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
  })

  it('brightens without ticking when the newest toucher advances and count stays level (full window)', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 10, count: 3 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 0 })
  })

  it('brightens and ticks when the count rises', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 10, count: 4 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 1 })
  })

  it('a re-anchor alone fades in', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 7, lastTouchRow: 9, count: 2 })
    expect(result.current).toEqual({ reanchor: 1, bump: 0, tick: 0 })
  })

  it('a re-anchor and a new touch in the same poll: the brighten wins', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 7, lastTouchRow: 10, count: 3 })
    expect(result.current).toEqual({ reanchor: 0, bump: 1, tick: 0 })
  })

  it('a falling count changes nothing', () => {
    const { result, rerender } = setup(base)
    rerender({ anchorRow: 5, lastTouchRow: 9, count: 2 })
    expect(result.current).toEqual({ reanchor: 0, bump: 0, tick: 0 })
  })
})
