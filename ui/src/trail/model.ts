import type { Step, StepKind } from '../graph/types'

/** The recorder keeps this many steps per session (recorder/memory.py RETAINED_CAP). */
export const RETAINED_STEPS = 500

/** Allowed, and not a secret read: the quiet default that folds into a group. */
export function isRoutine(step: Step): boolean {
  return step.verdict === 'allowed' && !step.sensitive
}

/** Blocks, warnings and highlights open a Why card. */
export function isAlarm(step: Step): boolean {
  return step.verdict === 'blocked' || step.verdict === 'warned' || step.verdict === 'highlighted'
}

export type TrailItem =
  | { type: 'step'; step: Step }
  | { type: 'group'; /** The first step's order: stable while the group grows at its end. */ key: number; steps: readonly Step[] }

/**
 * Fold each run of routine steps into one group. Blocks, warnings, highlights and
 * secret reads are never folded, and identical blocks stay separate rows.
 */
export function groupSteps(steps: readonly Step[]): TrailItem[] {
  const items: TrailItem[] = []
  let run: Step[] = []
  const flush = (): void => {
    if (run.length > 0) items.push({ type: 'group', key: run[0].order, steps: run })
    run = []
  }
  for (const step of steps) {
    if (isRoutine(step)) run.push(step)
    else {
      flush()
      items.push({ type: 'step', step })
    }
  }
  flush()
  return items
}

const KINDS: readonly StepKind[] = ['read', 'edit', 'shell', 'tool']

/** "4 read · 2 edit": counts by kind, in a fixed order, for a group's summary. */
export function kindCounts(steps: readonly Step[]): string {
  const parts: string[] = []
  for (const kind of KINDS) {
    const n = steps.filter((s) => s.kind === kind).length
    if (n > 0) parts.push(`${n} ${kind}`)
  }
  const other = steps.filter((s) => !KINDS.includes(s.kind)).length
  if (other > 0) parts.push(`${other} other`)
  return parts.join(' · ')
}

/** The cleaned thing a step touched: a path, a command or a tool name. */
export function what(step: Step): string {
  return step.file ?? step.command ?? step.tool ?? ''
}

/** "3-13" or "5": the order range a group covers. */
export function rangeLabel(steps: readonly Step[]): string {
  const first = steps[0].order
  const last = steps[steps.length - 1].order
  return first === last ? String(first) : `${first}–${last}`
}

export type AlarmKind = 'blocked' | 'warned' | 'highlighted'

export function alarmsOf(steps: readonly Step[], kind: AlarmKind): Step[] {
  return steps.filter((s) => s.verdict === kind)
}

/** The block or warning to select when nothing is picked: the newest block, else the newest alarm. */
export function newestAlarm(steps: readonly Step[]): Step | null {
  for (let i = steps.length - 1; i >= 0; i--) if (steps[i].verdict === 'blocked') return steps[i]
  for (let i = steps.length - 1; i >= 0; i--) if (isAlarm(steps[i])) return steps[i]
  return null
}

export type Trigger =
  /** No marking step applies to this step's rule: nothing is invented. */
  | { kind: 'none' }
  /** The recorder did not say which step marked the session (null, or restarted). */
  | { kind: 'unknown' }
  /** The marking step has dropped out of the last 500 steps. */
  | { kind: 'evicted'; order: number }
  | { kind: 'step'; step: Step }

/**
 * Which step led to this alarm. Only R1 has one: the step that made the session
 * "marked". Every other rule has no trigger step, and a trigger is never guessed
 * from the steps' own `sensitive` flag (the marking step can be a shell command).
 */
export function triggerFor(alarm: Step, steps: readonly Step[], markedOrder: number | null): Trigger {
  if (alarm.rule !== 'R1' || alarm.verdict !== 'blocked') return { kind: 'none' }
  if (markedOrder === null || markedOrder >= alarm.order) return { kind: 'unknown' }
  const found = steps.find((s) => s.order === markedOrder)
  return found === undefined ? { kind: 'evicted', order: markedOrder } : { kind: 'step', step: found }
}

/** What sits between the trigger and the alarm: routine steps and flagged ones, from the steps in memory. */
export function between(steps: readonly Step[], from: number, to: number): { routine: number; flagged: number } {
  let routine = 0
  let flagged = 0
  for (const s of steps) {
    if (s.order <= from || s.order >= to) continue
    if (isRoutine(s)) routine += 1
    else flagged += 1
  }
  return { routine, flagged }
}

/** Read-only commands the Why card shows instead of an "allow once" button (SPEC "How a rule changes"). */
export const RULE_COMMANDS: readonly string[] = [
  'agentfly rules draft …',
  'agentfly rules check',
  'sudo agentfly rules apply <draft>',
]
