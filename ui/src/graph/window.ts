import { enterDelay } from './choreography'
import type { PlacedStep, SecretSeen, Step } from './types'

export const WINDOW_SIZE = 20

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  /** The drawn window: at most 20 steps, ascending by row. */
  steps: PlacedStep[]
  /** Next row to hand out in this session. */
  nextRow: number
  secretSeen: SecretSeen | null
  /** Bumps whenever the window is reset, so the camera knows to jump. */
  epoch: number
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | { type: 'snapshot'; session: string | null; steps: Step[]; first?: boolean }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], nextRow: 0, secretSeen: null, epoch: 0, ignored }
}

function resetFrom(state: WindowState, ignored: string | null): WindowState {
  return { ...initialWindowState(ignored), epoch: state.epoch + 1 }
}

/** Field-wise equality; keys come from the objects so a new field cannot drift. */
function sameStep(a: PlacedStep, b: PlacedStep): boolean {
  const keys = Object.keys(a) as (keyof PlacedStep)[]
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
}

function newestOrder(steps: readonly { order: number }[]): number {
  return steps.reduce((max, s) => Math.max(max, s.order), -Infinity)
}

interface Merged {
  steps: PlacedStep[]
  nextRow: number
  secretSeen: SecretSeen | null
  changed: boolean
}

/**
 * Merge a poll into the held window. A known order updates in place and keeps
 * its row; an order above the newest held step is appended with the next row;
 * an unknown order below the newest held step is ignored (placing it would move
 * a box). Steps are sorted by order first.
 */
function merge(base: WindowState, incoming: readonly Step[], first: boolean): Merged {
  const sorted = [...incoming].sort((a, b) => a.order - b.order)
  const byOrder = new Map(base.steps.map((s) => [s.order, s]))
  let top = newestOrder(base.steps)
  let changed = false
  const updates = new Map<number, PlacedStep>()
  const appended: Step[] = []

  for (const step of sorted) {
    const known = byOrder.get(step.order)
    if (known !== undefined) {
      const next: PlacedStep = { ...known, ...step }
      if (!sameStep(known, next)) {
        updates.set(step.order, next)
        changed = true
      }
    } else if (step.order > top) {
      appended.push(step)
      top = step.order
    }
  }

  const placed: PlacedStep[] = appended.map((step, slot) => ({
    ...step,
    row: base.nextRow + slot,
    quiet: first,
    slot,
    of: appended.length,
  }))
  if (placed.length > 0) changed = true

  let secretSeen = base.secretSeen
  const fresh = new Set(placed)
  for (const s of [...updates.values(), ...placed]) {
    if (s.sensitive && secretSeen === null) {
      // A step already drawn (an update in place) has no entry of its own: the chip starts at once.
      secretSeen = fresh.has(s) ? { quiet: s.quiet, delay: enterDelay(s) } : { quiet: false, delay: 0 }
    }
  }
  if (secretSeen !== base.secretSeen) changed = true

  const steps = [...base.steps.map((s) => updates.get(s.order) ?? s), ...placed].slice(-WINDOW_SIZE)
  return { steps, nextRow: base.nextRow + placed.length, secretSeen, changed }
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === 'newSession') {
    if (state.session === null) return state
    return resetFrom(state, state.session)
  }

  const { session, steps, first = false } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hidden = session === null || session === ignored || steps.length === 0
  if (hidden) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return resetFrom(state, ignored)
  }

  // A new session, or numbering that went backwards (sessions.json deleted),
  // starts a fresh window. From an empty window (page load, or after a reset)
  // the first session is a plain start: the window is already fresh.
  const switched = state.session !== null && state.session !== session
  const restart = switched || newestOrder(steps) < newestOrder(state.steps)
  const base = restart ? resetFrom(state, ignored) : state
  const merged = merge(base, steps, first)

  if (!restart && !merged.changed && state.ignored === ignored) return state
  return {
    session,
    steps: merged.steps,
    nextRow: merged.nextRow,
    secretSeen: merged.secretSeen,
    epoch: base.epoch,
    ignored,
  }
}
