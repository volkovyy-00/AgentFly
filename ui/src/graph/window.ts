import { enterDelay } from './choreography'
import type { Group, Hidden, PlacedStep, SecretSeen, Step } from './types'

export const WINDOW_SIZE = 20

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  /** The drawn window: at most 20 steps, ascending by row. */
  steps: PlacedStep[]
  /** Next row to hand out in this session. */
  nextRow: number
  secretSeen: SecretSeen | null
  /** The summary counts and flagged older steps; null unless something is hidden. */
  group: Group | null
  /** Order of the step that made R1 mark the session (from the server); null when unknown. */
  markedOrder: number | null
  /** Bumps whenever the window is reset, so the camera knows to jump. */
  epoch: number
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | {
      type: 'snapshot'
      session: string | null
      steps: Step[]
      first?: boolean
      hidden?: Hidden | null
      flagged?: Step[]
      markedOrder?: number | null
    }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], nextRow: 0, secretSeen: null, group: null, markedOrder: null, epoch: 0, ignored }
}

function resetFrom(state: WindowState, ignored: string | null): WindowState {
  return { ...initialWindowState(ignored), epoch: state.epoch + 1 }
}

/** Field-wise equality; keys come from the objects so a new field cannot drift. */
function sameFields<T extends object>(a: T, b: T): boolean {
  const keys = Object.keys(a) as (keyof T)[]
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
}

function sameGroup(a: Group | null, b: Group | null): boolean {
  if (a === null || b === null) return a === b
  return (
    sameFields(a.hidden, b.hidden) &&
    a.flagged.length === b.flagged.length &&
    a.flagged.every((s, i) => sameFields(s, b.flagged[i]))
  )
}

function groupOf(hidden: Hidden | null, flagged: Step[]): Group | null {
  return hidden !== null && hidden.total > 0 ? { hidden, flagged } : null
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
function merge(base: WindowState, incoming: readonly Step[], first: boolean, markedOrder: number | null): Merged {
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
      if (!sameFields(known, next)) {
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
  if (secretSeen === null && markedOrder !== null) {
    // The server names the marking step: its own entry timing if it arrives in this poll,
    // still on the first response (a reload), otherwise at once.
    const marker = placed.find((s) => s.order === markedOrder)
    secretSeen = marker !== undefined ? { quiet: marker.quiet, delay: enterDelay(marker) } : { quiet: first, delay: 0 }
  }
  if (secretSeen === null) {
    // Fallback (no marked order, e.g. after a server restart): the first sensitive step seen.
    const fresh = new Set(placed)
    for (const s of [...updates.values(), ...placed]) {
      if (s.sensitive && secretSeen === null) {
        // A step already drawn (an update in place) has no entry of its own: the chip starts at once.
        secretSeen = fresh.has(s) ? { quiet: s.quiet, delay: enterDelay(s) } : { quiet: false, delay: 0 }
      }
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

  const { session, steps, first = false, hidden = null, flagged = [], markedOrder = null } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hiddenNow = session === null || session === ignored || steps.length === 0
  if (hiddenNow) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return resetFrom(state, ignored)
  }

  // A new session, or numbering that went backwards (sessions.json deleted),
  // starts a fresh window. From an empty window (page load, or after a reset)
  // the first session is a plain start: the window is already fresh.
  const switched = state.session !== null && state.session !== session
  const restart = switched || newestOrder(steps) < newestOrder(state.steps)
  const base = restart ? resetFrom(state, ignored) : state
  const merged = merge(base, steps, first, markedOrder)

  // The group and the marked order are replaced wholesale by every poll; only the
  // window steps are merged. Keep the old group object when nothing in it changed.
  const nextGroup = groupOf(hidden, flagged)
  const group = sameGroup(base.group, nextGroup) ? base.group : nextGroup

  if (
    !restart &&
    !merged.changed &&
    group === state.group &&
    markedOrder === state.markedOrder &&
    state.ignored === ignored
  ) {
    return state
  }
  return {
    session,
    // Keep the array when only the group or the marked order changed, so a memo or an
    // effect keyed on `steps` does not run for nothing.
    steps: merged.changed ? merged.steps : base.steps,
    nextRow: merged.nextRow,
    secretSeen: merged.secretSeen,
    group,
    markedOrder,
    epoch: base.epoch,
    ignored,
  }
}
