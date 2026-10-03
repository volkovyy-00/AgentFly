/** Every animation's timing in one pure table. Times are ms relative to a step's own start. */
export interface Span {
  start: number
  end: number
}

export const MAX_MS = 800
export const STAGGER_MAX_MS = 80
export const LAST_START_MS = 350
export const DIM_HOLD_MS = 1500

export const TIMING = {
  step: { start: 0, end: 200 },
  chain: { start: 150, end: 350 },
  edge: { start: 250, end: 450 },
  laneBox: { start: 250, end: 450 },
  secretRing: { start: 300, end: 800 },
  chip: { start: 300, end: 500 },
  borderWipe: { start: 100, end: 350 },
  blockEdge: { start: 250, end: 550 },
  ruleSpring: { start: 450, end: 800 },
  dimIn: { start: 0, end: 150 },
  dimHold: { start: 150, end: 1650 },
  dimOut: { start: 1650, end: 1950 },
  brighten: { start: 0, end: 300 },
  reanchor: { start: 0, end: 200 },
  banner: { start: 0, end: 300 },
} as const satisfies Record<string, Span>

/** The only entries allowed past 800 ms. */
export const EXEMPT = ['dimHold', 'dimOut'] as const

export const dur = (span: Span): number => span.end - span.start

/** ms to seconds, the unit motion's transitions take. */
export const sec = (n: number): number => n / 1000

/** Start offset of the `slot`-th of `of` steps that arrived in one poll. */
export function stagger(slot: number, of: number): number {
  if (of <= 1) return 0
  return slot * Math.min(STAGGER_MAX_MS, LAST_START_MS / (of - 1))
}

export function enterDelay(step: { quiet: boolean; slot: number; of: number }): number {
  return step.quiet ? 0 : stagger(step.slot, step.of)
}
