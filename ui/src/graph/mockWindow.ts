import type { Hidden, Step, Verdict } from './types'

export const FLAG_CAP = 5
export const MOCK_CAP = 500

const ALARMS: readonly Verdict[] = ['blocked', 'warned']
const isAlarm = (s: Step): boolean => ALARMS.includes(s.verdict)

export interface MockWindow {
  steps: Step[]
  hidden: Hidden
  flagged: Step[]
  markedOrder: number | null
}

function tally(steps: readonly Step[]): Hidden {
  const h: Hidden = { total: 0, read: 0, shell: 0, edit: 0, tool: 0, blocked: 0, warned: 0 }
  for (const s of steps) {
    h.total += 1
    if (s.kind === 'read' || s.kind === 'shell' || s.kind === 'edit' || s.kind === 'tool') h[s.kind] += 1
    if (s.verdict === 'blocked' || s.verdict === 'warned') h[s.verdict] += 1
  }
  return h
}

/** Port of recorder/memory.py `pick_flagged`; tests/fixtures/window_golden.json holds the two together. */
export function pickFlagged(marking: Step | null, candidates: Iterable<Step>, floor: number, cap = FLAG_CAP): Step[] {
  const picked = new Map<number, Step>()
  if (marking !== null && marking.order < floor) picked.set(marking.order, marking)
  for (const step of candidates) {
    if (picked.size >= cap) break
    if (step.order < floor && !picked.has(step.order)) picked.set(step.order, step)
  }
  return [...picked.values()].sort((a, b) => a.order - b.order)
}

/**
 * What the server's `GET /api/steps?limit=N` would return after `all` steps were
 * recorded, with the same retained `cap` and the order of the step that made R1
 * mark the session. Mock mode uses it so the page needs no server.
 */
export function windowOfMock(all: readonly Step[], limit: number, cap: number, markedOrder: number | null): MockWindow {
  const retained = all.slice(-cap)
  const steps = retained.slice(-limit)
  if (steps.length === 0) return { steps: [], hidden: tally([]), flagged: [], markedOrder: null }

  const floor = steps[0].order
  const everything = tally(all)
  const inWindow = tally(steps)
  const hidden = Object.fromEntries(
    (Object.keys(everything) as (keyof Hidden)[]).map((k) => [k, everything[k] - inWindow[k]]),
  ) as unknown as Hidden

  const marking = markedOrder === null ? null : (all.find((s) => s.order === markedOrder) ?? null)
  // The server keeps the newest 5 alarms among the steps the cap pushed out.
  const evicted = all.slice(0, all.length - retained.length).filter(isAlarm).slice(-FLAG_CAP)
  function* candidates(): Generator<Step> {
    for (let i = retained.length - 1; i >= 0; i--) {
      if (retained[i].order < floor && isAlarm(retained[i])) yield retained[i]
    }
    for (let i = evicted.length - 1; i >= 0; i--) yield evicted[i]
  }
  return { steps, hidden, flagged: pickFlagged(marking, candidates(), floor), markedOrder: marking?.order ?? null }
}
