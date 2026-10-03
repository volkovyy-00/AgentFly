export type Verdict = 'allowed' | 'blocked' | 'warned'
export type StepKind = 'read' | 'shell' | 'edit' | 'tool'

/** One cleaned step, as `GET /api/steps` returns it (recorder/memory.py). */
export interface Step {
  order: number
  kind: StepKind
  verdict: Verdict
  tool: string | null
  file: string | null
  sensitive: boolean
  command: string | null
  host: string | null
  rule: string | null
}

/** A step plus where and how it first appeared on this page (window.ts sets these once). */
export interface PlacedStep extends Step {
  /** Canvas row, fixed when the step is first seen. */
  row: number
  /** From the page's first response: drawn without motion. */
  quiet: boolean
  /** Index within the poll that appended it. */
  slot: number
  /** How many steps that poll appended. */
  of: number
}

/** Set once a sensitive step is seen; `quiet` if it came in the first response. */
export interface SecretSeen {
  quiet: boolean
  /** The secret step's own start (its stagger, ms after the poll), so the chip follows its box. */
  delay: number
}

/** Counts of the steps outside the window (recorder/memory.py `hidden`). */
export interface Hidden {
  total: number
  read: number
  shell: number
  edit: number
  tool: number
  blocked: number
  warned: number
}

export const STEP_KINDS: readonly StepKind[] = ['read', 'shell', 'edit', 'tool']
export const HIDDEN_KEYS = ['total', 'read', 'shell', 'edit', 'tool', 'blocked', 'warned'] as const satisfies readonly (keyof Hidden)[]

/** A `hidden` count object with every key at zero. */
export function emptyHidden(): Hidden {
  return { total: 0, read: 0, shell: 0, edit: 0, tool: 0, blocked: 0, warned: 0 }
}

/** What sits above the window: the counts and the older landmark steps. */
export interface Group {
  hidden: Hidden
  flagged: readonly Step[]
}

export interface Snapshot {
  session: string | null
  steps: Step[]
  /** null when the server sent no `hidden` (mock, older server): no group. */
  hidden: Hidden | null
  flagged: Step[]
  /** Order of the step that made R1 mark the session; null when unknown. */
  markedOrder: number | null
}
