import { useCallback, useEffect, useReducer, useState } from 'react'
import { readIgnored, writeIgnored } from './ignoredSession'
import { MOCK_STEPS } from './mock'
import { parseSnapshot } from './snapshot'
import type { Step } from './types'
import { initialWindowState, windowReducer } from './window'

export const POLL_GAP_MS = 1000
export const POLL_TIMEOUT_MS = 1500
export const MOCK_INTERVAL_MS = 1500

export interface Recorder {
  steps: readonly Step[]
  offline: boolean
  newSession: () => void
}

/**
 * The page's data source. Real mode polls GET /api/steps: one request, then a
 * 1 s gap, aborting after 1.5 s; one failure sets `offline` (worst case 2.5 s
 * after the server stops) and the last steps stay. Mock mode replays MOCK_STEPS
 * and never calls the server.
 */
export function useRecorder(mock: boolean): Recorder {
  const [state, dispatch] = useReducer(windowReducer, undefined, () =>
    initialWindowState(mock ? null : readIgnored()),
  )
  const [offline, setOffline] = useState(false)
  const [mockRun, setMockRun] = useState(0)

  useEffect(() => {
    if (!mock) writeIgnored(state.ignored)
  }, [mock, state.ignored])

  useEffect(() => {
    if (mock) return
    let cancelled = false
    let gap: ReturnType<typeof setTimeout> | undefined
    let active: AbortController | undefined

    async function poll(): Promise<void> {
      const controller = new AbortController()
      active = controller
      const abortTimer = setTimeout(() => controller.abort(), POLL_TIMEOUT_MS)
      try {
        const response = await fetch('/api/steps', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('bad status')
        const snapshot = parseSnapshot(await response.json())
        if (snapshot === null) throw new Error('bad body')
        if (cancelled) return
        setOffline(false)
        dispatch({ type: 'snapshot', session: snapshot.session, steps: snapshot.steps })
      } catch {
        if (!cancelled) setOffline(true)
      } finally {
        clearTimeout(abortTimer)
        if (!cancelled) gap = setTimeout(() => void poll(), POLL_GAP_MS)
      }
    }

    void poll()
    return () => {
      cancelled = true
      clearTimeout(gap)
      active?.abort()
    }
  }, [mock])

  useEffect(() => {
    if (!mock) return
    const session = `mock-${mockRun}`
    let shown = 0
    function tick(): void {
      shown += 1
      dispatch({ type: 'snapshot', session, steps: MOCK_STEPS.slice(0, shown) as Step[] })
      if (shown >= MOCK_STEPS.length) clearInterval(timer)
    }
    const timer = setInterval(tick, MOCK_INTERVAL_MS)
    tick()
    return () => clearInterval(timer)
  }, [mock, mockRun])

  const newSession = useCallback(() => {
    if (mock) setMockRun((n) => n + 1)
    else dispatch({ type: 'newSession' })
  }, [mock])

  return { steps: state.steps, offline: mock ? false : offline, newSession }
}
