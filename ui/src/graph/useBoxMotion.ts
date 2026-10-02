import { useEffect, useRef, useState } from 'react'
import type { BoxMeta } from './layout'

export interface BoxMotion {
  /** Times the box jumped to a new anchor row (fade it in). */
  reanchor: number
  /** Times it was reused (brighten it). */
  bump: number
  /** Times its count rose (tick the number). */
  tick: number
}

/**
 * Triggers for a lane box that is already mounted. Brighten follows the newest
 * toucher's row (a full window drops one toucher and adds one, so the count can
 * stay level); the number ticks only when the count rises; a re-anchor in the
 * same poll as a new touch is skipped: the brighten wins.
 */
export function useBoxMotion({ anchorRow, lastTouchRow, count }: Pick<BoxMeta, 'anchorRow' | 'lastTouchRow' | 'count'>): BoxMotion {
  const previous = useRef({ anchorRow, lastTouchRow, count })
  const [motion, setMotion] = useState<BoxMotion>({ reanchor: 0, bump: 0, tick: 0 })

  useEffect(() => {
    const was = previous.current
    previous.current = { anchorRow, lastTouchRow, count }
    const touched = lastTouchRow > was.lastTouchRow
    const moved = anchorRow !== was.anchorRow
    const risen = count > was.count
    if (!touched && !moved && !risen) return
    setMotion((m) => ({
      reanchor: m.reanchor + (moved && !touched ? 1 : 0),
      bump: m.bump + (touched ? 1 : 0),
      tick: m.tick + (risen ? 1 : 0),
    }))
  }, [anchorRow, lastTouchRow, count])

  return motion
}
