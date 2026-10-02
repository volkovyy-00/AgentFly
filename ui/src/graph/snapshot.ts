import type { Snapshot, Step, StepKind, Verdict } from './types'

const VERDICTS: readonly string[] = ['allowed', 'blocked', 'warned']

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function parseStep(raw: unknown): Step | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  if (typeof r.order !== 'number' || !Number.isFinite(r.order)) return null
  if (typeof r.kind !== 'string' || typeof r.verdict !== 'string') return null
  // A newer server may send a kind or verdict this page does not know. Show the
  // step anyway (a flight recorder must not hide events): the kind as text, an
  // unknown verdict as WARN.
  return {
    order: r.order,
    kind: r.kind as StepKind,
    verdict: VERDICTS.includes(r.verdict) ? (r.verdict as Verdict) : 'warned',
    tool: text(r.tool),
    file: text(r.file),
    sensitive: r.sensitive === true,
    command: text(r.command),
    host: text(r.host),
    rule: text(r.rule),
  }
}

/**
 * Turn a parsed `/api/steps` body into a Snapshot. Returns null when the body
 * is not an object (the caller treats that as a failed poll). Steps without a
 * numeric `order`, a `kind` or a `verdict` are dropped; a missing `steps` array
 * is an empty list (as on the old page).
 */
export function parseSnapshot(raw: unknown): Snapshot | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const session = typeof r.session === 'string' ? r.session : null
  const steps = Array.isArray(r.steps)
    ? r.steps.map(parseStep).filter((s): s is Step => s !== null)
    : []
  return { session, steps }
}
