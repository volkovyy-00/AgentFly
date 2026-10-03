import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { TIMING, dur, enterDelay } from './choreography'
import { hotIds } from './layout'
import type { PlacedStep } from './types'

export interface DimState {
  active: boolean
  /** Ids that stay bright while `active`. */
  hot: ReadonlySet<string>
}

const OFF: DimState = { active: false, hot: new Set() }

export const DimContext = createContext<DimState>(OFF)

/** True for a node or edge that should be dimmed right now. Applied per element, never on a container. */
export function useDimmed(id: string): boolean {
  const { active, hot } = useContext(DimContext)
  return active && !hot.has(id)
}

/**
 * Starts a dim for the newest non-quiet blocked step that newly appears. The
 * timer starts at that step's own entry delay. A second block restarts the
 * hold, so dims never stack. The hold is not scaled by `ms`: under reduced
 * motion the dim is instant but still lasts 1.5 s.
 */
export function useBlockDim(steps: readonly PlacedStep[], epoch: number, ms: (n: number) => number): DimState {
  const [state, setState] = useState<DimState>(OFF)
  // The newest row seen, per epoch: a reset restarts rows at 0, so a row only
  // means something within its epoch.
  const handled = useRef({ epoch, row: -1 })
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const clear = useCallback(() => {
    for (const timer of timers.current) clearTimeout(timer)
    timers.current = []
  }, [])

  // A layout effect: a new block must not paint dimmed for a frame under the
  // previous block's hot set.
  useLayoutEffect(() => {
    if (handled.current.epoch !== epoch) {
      clear()
      setState(OFF)
      handled.current = { epoch, row: -1 }
    }
    const was = handled.current.row
    handled.current = { epoch, row: steps.at(-1)?.row ?? -1 }
    const block = steps.filter((s) => s.row > was && !s.quiet && s.verdict === 'blocked').at(-1)
    if (block === undefined) return
    clear()
    const hot = hotIds(block)
    // During a running dim the new block takes over the bright set at once; only
    // the first dim waits for the block's own start.
    setState((s) => (s.active ? { active: true, hot } : s))
    const start = ms(enterDelay(block))
    timers.current.push(
      setTimeout(() => setState({ active: true, hot }), start),
      // The hold is a state, not movement: it keeps its 1.5 s under reduced motion.
      setTimeout(() => setState(OFF), start + ms(TIMING.dimIn.end) + dur(TIMING.dimHold)),
    )
  }, [steps, epoch]) // Not `ms`: a reduced-motion toggle (a new `ms`) must not re-run it.

  useEffect(() => clear, [clear])

  return state
}
