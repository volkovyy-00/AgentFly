import type { Hidden } from './types'

const KINDS = ['read', 'shell', 'edit', 'tool'] as const

/**
 * The summary box text: "38 earlier steps (2 blocked, 1 warned): 20 read, 16 shell".
 * Zero counts are dropped. The alarms come first and in brackets because they overlay the kind
 * counts (they are not a partition) and are what must survive a truncated box.
 */
export function summaryText(h: Hidden): string {
  const head = `${h.total} earlier ${h.total === 1 ? 'step' : 'steps'}`
  const alarms = [h.blocked > 0 ? `${h.blocked} blocked` : null, h.warned > 0 ? `${h.warned} warned` : null].filter(
    (a): a is string => a !== null,
  )
  const kinds = KINDS.filter((k) => h[k] > 0).map((k) => `${h[k]} ${k}`)
  return `${head}${alarms.length > 0 ? ` (${alarms.join(', ')})` : ''}${kinds.length > 0 ? `: ${kinds.join(', ')}` : ''}`
}
