import { HIDDEN_KEYS, type Hidden, type Snapshot, type Step, type StepKind, type Verdict } from './types'

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

function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

/** null when `hidden` is absent (no group); undefined when it is malformed (a bad body). */
function parseHidden(raw: unknown): Hidden | null | undefined {
  if (raw === undefined || raw === null) return null
  if (typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const r = raw as Record<string, unknown>
  const out = {} as Hidden
  for (const key of HIDDEN_KEYS) {
    const n = count(r[key])
    if (n === null) return undefined
    out[key] = n
  }
  return out
}

/**
 * Turn a parsed `/api/steps` body into a Snapshot. Returns null when the body
 * is not a plain object with a `steps` array, or when `hidden`, `flagged` or
 * `marked_order` is present but malformed (the caller treats null as a failed
 * poll / OFFLINE). Steps without a numeric `order`, a `kind` or a `verdict` are
 * dropped, in `steps` and in `flagged` alike; an explicit empty `steps` list is
 * valid. A missing `hidden` means no group (the mock, an older server).
 */
export function parseSnapshot(raw: unknown): Snapshot | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  if (!Array.isArray(r.steps)) return null
  const session = typeof r.session === 'string' ? r.session : null
  const steps = r.steps.map(parseStep).filter((s): s is Step => s !== null)

  const hidden = parseHidden(r.hidden)
  if (hidden === undefined) return null

  let flagged: Step[] = []
  if (r.flagged !== undefined && r.flagged !== null) {
    if (!Array.isArray(r.flagged)) return null
    flagged = r.flagged.map(parseStep).filter((s): s is Step => s !== null)
  }

  const marked = r.marked_order
  if (marked !== undefined && marked !== null && !Number.isInteger(marked)) return null

  return { session, steps, hidden, flagged, markedOrder: typeof marked === 'number' ? marked : null }
}
