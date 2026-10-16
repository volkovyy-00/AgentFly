import { useEffect, useRef, useState } from 'react'
import { LONG_MARKED_ORDER, longSession } from '../graph/mock'
import { parseSnapshot } from '../graph/snapshot'
import type { Step } from '../graph/types'
import { RETAINED_STEPS } from './model'

export const POLL_GAP_MS = 1000
export const POLL_TIMEOUT_MS = 1500
export const MOCK_INTERVAL_MS = 1500

/** What `/health` sends beyond `ok`. Both arrive from a later recorder card; absent means hidden. */
export interface Health {
  lastHookAt: Date | null
  offlineGuardCount: number | null
}

export interface Trail {
  steps: readonly Step[]
  session: string | null
  /** Order of the step that made R1 mark the session; null when unknown. */
  markedOrder: number | null
  offline: boolean
  /** True after the first response (or mock tick): tells "waiting" from "connecting". */
  loaded: boolean
  health: Health
}

const NO_HEALTH: Health = { lastHookAt: null, offlineGuardCount: null }

export function parseHealth(raw: unknown): Health {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return NO_HEALTH
  const r = raw as Record<string, unknown>
  let lastHookAt: Date | null = null
  if (typeof r.last_hook_at === 'string') {
    const d = new Date(r.last_hook_at)
    if (!Number.isNaN(d.getTime())) lastHookAt = d
  }
  const n = r.offline_guard_count
  const offlineGuardCount = typeof n === 'number' && Number.isInteger(n) && n >= 0 ? n : null
  return { lastHookAt, offlineGuardCount }
}

async function getJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error('bad status')
  return response.json()
}

/**
 * Mock session for `?view=trail&mock=1&len=N`: `longSession`, but ordered from 1 like real
 * sessions, and cut to the last 500 steps like the recorder's memory. The marking step
 * (the `.env` read) is remembered even after it drops out of the 500.
 */
export function trailMock(len: number, rich: boolean): { steps: Step[]; markedOrder: number } {
  const steps = longSession(len).map((s) => {
    const mapped: Step = { ...s, order: s.order - 40000 + 1 }
    if (rich && mapped.verdict === 'blocked') {
      mapped.rule_text = 'Blocked by rule R1: a secret was read earlier in this session, and now data is being sent out.'
      mapped.user_message = mapped.rule_text
      mapped.agent_message = `${mapped.rule_text} Do not retry with another tool or language. Stop and tell the user.`
    }
    if (rich && mapped.order % 47 === 0 && mapped.verdict === 'allowed' && !mapped.sensitive) {
      mapped.verdict = 'highlighted'
      mapped.rule = 'H1'
    }
    return mapped
  })
  return { steps, markedOrder: LONG_MARKED_ORDER - 40000 + 1 }
}

/**
 * The trail's data source. Real mode polls once a second, two requests per poll:
 * `GET /api/steps?all=1` for the steps (up to 500) and `GET /api/steps?limit=1`
 * for `marked_order`, which `?all=1` does not send. The marker is used only when
 * both bodies name the same session. A failed or malformed steps request sets
 * `offline` (the last steps stay); a failed marker or `/health` request only
 * hides what it would have added. Mock mode never calls the server.
 */
export function useTrail(mock: boolean, len: number, burst: number, rich: boolean): Trail {
  const [state, setState] = useState<Omit<Trail, 'offline' | 'health'>>({
    steps: [],
    session: null,
    markedOrder: null,
    loaded: false,
  })
  const [offline, setOffline] = useState(false)
  const [health, setHealth] = useState<Health>(NO_HEALTH)
  const lastMarker = useRef<{ session: string | null; order: number | null }>({ session: null, order: null })

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
        const [stepsBody, markerBody, healthBody] = await Promise.all([
          getJson('/api/steps?all=1', controller.signal),
          getJson('/api/steps?limit=1', controller.signal).catch(() => null),
          getJson('/health', controller.signal).catch(() => null),
        ])
        const snapshot = parseSnapshot(stepsBody)
        if (snapshot === null) throw new Error('bad body')
        if (cancelled) return
        const marker = markerBody === null ? null : parseSnapshot(markerBody)
        if (marker !== null && marker.session === snapshot.session) {
          lastMarker.current = { session: snapshot.session, order: marker.markedOrder }
        } else if (lastMarker.current.session !== snapshot.session) {
          lastMarker.current = { session: snapshot.session, order: null }
        }
        setOffline(false)
        setHealth(parseHealth(healthBody))
        setState({ steps: snapshot.steps, session: snapshot.session, markedOrder: lastMarker.current.order, loaded: true })
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
    const { steps: all, markedOrder } = trailMock(len, rich)
    let shown = 0
    function tick(): void {
      shown = Math.min(shown + burst, all.length)
      const kept = all.slice(Math.max(0, shown - RETAINED_STEPS), shown)
      setState({ steps: kept, session: 'mock-0', markedOrder: shown >= 2 ? markedOrder : null, loaded: true })
      if (shown >= all.length) clearInterval(timer)
    }
    const timer = setInterval(tick, MOCK_INTERVAL_MS)
    tick()
    return () => clearInterval(timer)
  }, [mock, len, burst, rich])

  return { ...state, offline: mock ? false : offline, health: mock ? NO_HEALTH : health }
}
