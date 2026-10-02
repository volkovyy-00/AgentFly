import type { Step } from './types'

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
