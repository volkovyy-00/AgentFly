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

export interface Snapshot {
  session: string | null
  steps: Step[]
}
