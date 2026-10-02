import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout'
import { stepsFrom } from './testing'
import { computeViewport } from './viewport'
import { initialWindowState, windowReducer, WINDOW_SIZE, type WindowState } from './window'

const PANE = { width: 960, height: 1080 }

/** The newest step's box must sit fully inside the pane at the computed camera. */
function newestStepInView(state: WindowState): boolean {
  const layout = layoutGraph(state.steps)
  const vp = computeViewport(layout.rowCount, PANE)
  const newest = state.steps.at(-1)
  const box = layout.nodes.find((n) => n.id === `step:${newest?.order}`)
  if (box === undefined) return false
  const top = box.position.y * vp.zoom + vp.y
  const bottom = top + (box.height ?? 0) * vp.zoom
  const left = box.position.x * vp.zoom + vp.x
  const right = left + (box.width ?? 0) * vp.zoom
  return top >= 0 && bottom <= PANE.height && left >= 0 && right <= PANE.width
}

describe('the newest step stays in view as polls arrive (real-sized orders)', () => {
  it('follows from the first 10 steps through 30 more', () => {
    // Each poll brings the server's last 10 steps, as GET /api/steps does.
    const polls = [
      stepsFrom(40000, 10),
      stepsFrom(40005, 10),
      stepsFrom(40010, 10),
      stepsFrom(40020, 10),
      stepsFrom(40030, 10),
      stepsFrom(40040, 10),
    ]
    let state = initialWindowState()
    for (const steps of polls) {
      state = windowReducer(state, { type: 'snapshot', session: 's', steps })
      expect(state.steps.length).toBeLessThanOrEqual(WINDOW_SIZE)
      expect(newestStepInView(state), `after orders up to ${state.steps.at(-1)?.order}`).toBe(true)
    }
    expect(state.steps.at(-1)?.order).toBe(40049)
    expect(state.steps).toHaveLength(WINDOW_SIZE)
  })

  it('keeps the newest step in view when the pane is shorter than the window', () => {
    let state = initialWindowState()
    state = windowReducer(state, { type: 'snapshot', session: 's', steps: stepsFrom(40000, 10) })
    state = windowReducer(state, { type: 'snapshot', session: 's', steps: stepsFrom(40010, 10) })
    const layout = layoutGraph(state.steps)
    const short = { width: 960, height: 600 }
    const vp = computeViewport(layout.rowCount, short)
    const box = layout.nodes.find((n) => n.id === 'step:40019')!
    expect(box.position.y + vp.y + (box.height ?? 0)).toBeLessThanOrEqual(short.height)
    expect(box.position.y + vp.y).toBeGreaterThanOrEqual(0)
  })

  it('keeps the newest step in view in a 644-wide pane through the same polls', () => {
    const narrow = { width: 644, height: 1080 }
    const inView = (state: WindowState): boolean => {
      const layout = layoutGraph(state.steps)
      const vp = computeViewport(layout.rowCount, narrow)
      const newest = state.steps.at(-1)
      const box = layout.nodes.find((n) => n.id === `step:${newest?.order}`)
      if (box === undefined) return false
      const top = box.position.y * vp.zoom + vp.y
      const bottom = top + (box.height ?? 0) * vp.zoom
      const left = box.position.x * vp.zoom + vp.x
      const right = left + (box.width ?? 0) * vp.zoom
      return top >= 0 && bottom <= narrow.height && left >= 0 && right <= narrow.width
    }
    const polls = [
      stepsFrom(40000, 10),
      stepsFrom(40005, 10),
      stepsFrom(40010, 10),
      stepsFrom(40020, 10),
      stepsFrom(40030, 10),
      stepsFrom(40040, 10),
    ]
    let state = initialWindowState()
    for (const steps of polls) {
      state = windowReducer(state, { type: 'snapshot', session: 's', steps })
      expect(inView(state), `after orders up to ${state.steps.at(-1)?.order}`).toBe(true)
    }
  })
})
