import type { Step } from './types'

export const WINDOW_SIZE = 20

function newestOrder(steps: readonly Step[]): number {
  return steps.reduce((max, s) => Math.max(max, s.order), -Infinity)
}

function windowOf(steps: Iterable<Step>): Step[] {
  const byOrder = new Map<number, Step>()
  for (const step of steps) byOrder.set(step.order, step)
  return [...byOrder.values()].sort((a, b) => a.order - b.order).slice(-WINDOW_SIZE)
}

/**
 * Merge a poll's steps into the held window, by `order`, keeping the newest 20.
 * If the incoming steps are older than the held ones (the server's numbering
 * went backwards, for example sessions.json was deleted), replace the window.
 */
export function mergeSteps(held: readonly Step[], incoming: readonly Step[]): Step[] {
  if (incoming.length === 0) return [...held]
  if (held.length > 0 && newestOrder(incoming) < newestOrder(held)) return windowOf(incoming)
  return windowOf([...held, ...incoming])
}

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  steps: Step[]
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | { type: 'snapshot'; session: string | null; steps: Step[] }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], ignored }
}

function sameSteps(a: readonly Step[], b: readonly Step[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === 'newSession') {
    if (state.session === null) return state
    return { session: null, steps: [], ignored: state.session }
  }

  const { session, steps } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hidden = session === null || session === ignored || steps.length === 0
  if (hidden) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return { session: null, steps: [], ignored }
  }

  const base = state.session === session ? state.steps : []
  const merged = mergeSteps(base, steps)
  if (state.session === session && state.ignored === ignored && sameSteps(state.steps, merged)) {
    return state
  }
  return { session, steps: merged, ignored }
}
