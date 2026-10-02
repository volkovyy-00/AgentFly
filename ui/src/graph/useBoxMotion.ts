import { useLayoutEffect, useRef, useState } from 'react'
import type { BoxMeta } from './layout'

export interface BoxMotion {
  /** Times the box jumped to a new anchor row (fade it in). */
  reanchor: number
  /** Times it was reused (brighten it). */
  bump: number
  /** Times its count rose (tick the number). */
  tick: number
  /**
   * `bump` and `tick` when the box last re-anchored. A re-anchor remounts the
   * box's inner element, so the brighten and the tick replay only above these.
   */
  anchoredAt: { bump: number; tick: number }
}

/**
 * Triggers for a lane box that is already mounted. Brighten follows the newest
 * toucher's row (a full window drops one toucher and adds one, so the count can
 * stay level); the number ticks only when the count rises; a re-anchor in the
 * same poll as a new touch is skipped: the brighten wins.
 */
export function useBoxMotion({ anchorRow, lastTouchRow, count }: Pick<BoxMeta, 'anchorRow' | 'lastTouchRow' | 'count'>): BoxMotion {
  const previous = useRef({ anchorRow, lastTouchRow, count })
  const [motion, setMotion] = useState<BoxMotion>({ reanchor: 0, bump: 0, tick: 0, anchoredAt: { bump: 0, tick: 0 } })

  // A layout effect: the new count or anchor must not paint at full strength for one frame before the animation remounts.
  useLayoutEffect(() => {
    const was = previous.current
    previous.current = { anchorRow, lastTouchRow, count }
    const touched = lastTouchRow > was.lastTouchRow
    const moved = anchorRow !== was.anchorRow
    const risen = count > was.count
    if (!touched && !moved && !risen) return
    const reanchored = moved && !touched
    setMotion((m) => ({
      reanchor: m.reanchor + (reanchored ? 1 : 0),
      bump: m.bump + (touched ? 1 : 0),
      tick: m.tick + (risen ? 1 : 0),
      anchoredAt: reanchored ? { bump: m.bump, tick: m.tick } : m.anchoredAt,
    }))
  }, [anchorRow, lastTouchRow, count])

  return motion
}
