import type { Hidden, PlacedStep, Step } from './types'

/** A plain allowed shell step; override fields as needed. */
export function makeStep(order: number, over: Partial<Step> = {}): Step {
  return {
    order,
    kind: 'shell',
    verdict: 'allowed',
    tool: null,
    file: null,
    sensitive: false,
    command: 'ls',
    host: null,
    rule: null,
    ...over,
  }
}

/** `count` plain steps with consecutive orders from `first`. */
export function stepsFrom(first: number, count: number, over: Partial<Step> = {}): Step[] {
  return Array.from({ length: count }, (_, i) => makeStep(first + i, over))
}

/** Steps as the window would place them: consecutive rows from `firstRow`. */
export function place(steps: readonly Step[], firstRow = 0, over: Partial<PlacedStep> = {}): PlacedStep[] {
  return steps.map((s, i) => ({ ...s, row: firstRow + i, quiet: false, slot: 0, of: 1, ...over }))
}

/** A `hidden` count object: all zeros unless overridden. */
export function makeHidden(over: Partial<Hidden> = {}): Hidden {
  return { total: 0, read: 0, shell: 0, edit: 0, tool: 0, blocked: 0, warned: 0, ...over }
}
