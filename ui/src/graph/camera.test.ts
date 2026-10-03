import { describe, expect, it } from 'vitest'
import {
  CLICK_SLOP, FALLBACK_PANE, INITIAL_GESTURE, MIN_ZOOM, SLIDE_MS, clampViewport, decideMove, easeOutCubic,
  followTarget, gestureStep, hasAlarm, movedFrom, panExtent, resolvePane, rowsOf, slideOptions, zoomFor, type Gesture,
} from './camera'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD, layoutGraph, stepId } from './layout'
import { makeStep, place, stepsFrom } from './testing'
import { initialWindowState, windowReducer, type WindowState } from './window'

const PANE = { width: 960, height: 1080 }

describe('zoomFor', () => {
  it.each([932, 960, 3000])('is 1 when the pane is at least as wide as the content (%i)', (w) => {
    expect(zoomFor(w)).toBe(1)
  })
  it('scales down to fit, with a floor', () => {
    expect(zoomFor(644)).toBeCloseTo(644 / CONTENT_W)
    expect(zoomFor(300)).toBe(MIN_ZOOM)
  })
})

describe('resolvePane', () => {
  it.each([
    { width: 0, height: 0 },
    { width: Number.NaN, height: Number.NaN },
    { width: -5, height: Infinity },
  ])('falls back to 960x1080 for an unmeasured pane %j', (pane) => {
    expect(resolvePane(pane)).toEqual(FALLBACK_PANE)
    const vp = followTarget({ first: 0, last: 19 }, pane)
    expect(Object.values(vp).every(Number.isFinite)).toBe(true)
  })
})

describe('followTarget', () => {
  it('starts at the top padding for a short session', () => {
    expect(followTarget({ first: 0, last: -1 }, PANE)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
    expect(followTarget({ first: 0, last: 4 }, PANE)).toEqual({ x: 0, y: TOP_PAD, zoom: 1 })
  })

  it('puts the first drawn row at the top padding even when it is row 40,000', () => {
    const vp = followTarget({ first: 40000, last: 40004 }, PANE)
    expect(40000 * ROW_PITCH + vp.y).toBe(TOP_PAD)
  })

  it('follows the newest row once rows outgrow the pane', () => {
    const vp = followTarget({ first: 100, last: 119 }, PANE)
    expect(120 * ROW_PITCH + vp.y).toBe(PANE.height - BOTTOM_PAD)
  })

  it('scales and keeps the content inside a 644-wide pane', () => {
    const vp = followTarget({ first: 0, last: 4 }, { width: 644, height: 1080 })
    expect(vp.zoom).toBeCloseTo(644 / CONTENT_W)
    expect(vp.x).toBeCloseTo(0)
  })
})

describe('panExtent', () => {
  it('spans the drawn rows plus the pads, divided by zoom', () => {
    // A 600 px tall pane, so 20 rows at zoom 0.69 outgrow it and the pads show.
    const pane = { width: 644, height: 600 }
    const z = zoomFor(644)
    const [[x0, y0], [x1, y1]] = panExtent({ first: 100, last: 119 }, pane)
    expect(x0).toBeCloseTo(0)
    expect(x1).toBeCloseTo(644 / z)
    expect(y0).toBeCloseTo(100 * ROW_PITCH - TOP_PAD / z)
    expect(y1).toBeCloseTo(120 * ROW_PITCH + BOTTOM_PAD / z)
  })

  it('is at least as tall as the pane, so d3 never centres a short session', () => {
    const [[, y0], [, y1]] = panExtent({ first: 0, last: 2 }, PANE)
    expect(y1 - y0).toBeGreaterThanOrEqual(PANE.height)
    expect(y0).toBe(-TOP_PAD)
  })

  it('leaves no room to pan sideways', () => {
    const [[x0], [x1]] = panExtent({ first: 0, last: 30 }, PANE)
    expect(x1 - x0).toBeCloseTo(PANE.width)
  })

  it('has the follow target inside it, touching the bottom edge when rows outgrow the pane', () => {
    const rows = { first: 100, last: 119 }
    const vp = followTarget(rows, PANE)
    const [[, y0], [, y1]] = panExtent(rows, PANE)
    expect(-vp.y / vp.zoom).toBeGreaterThanOrEqual(y0)
    expect((PANE.height - vp.y) / vp.zoom).toBeCloseTo(y1)
  })
})

describe('clampViewport', () => {
  const rows = { first: 100, last: 119 }
  const extent = panExtent(rows, PANE)

  it('returns the same viewport when it is inside the extent', () => {
    const vp = followTarget(rows, PANE)
    expect(clampViewport(vp, extent, PANE)).toBe(vp)
  })

  it('pulls a viewer who scrolled above the first row back to the top, with no NaN', () => {
    const clamped = clampViewport({ x: 0, y: 9999, zoom: 1 }, extent, PANE)
    expect(-clamped.y).toBe(extent[0][1])
    expect(Number.isFinite(clamped.y)).toBe(true)
  })

  it('pulls a viewer who scrolled below the newest row back up', () => {
    const clamped = clampViewport({ x: 0, y: -99999, zoom: 1 }, extent, PANE)
    expect(-clamped.y + PANE.height).toBe(extent[1][1])
  })
})

describe('hasAlarm and decideMove', () => {
  const blocked = (row: number, quiet = false) =>
    place([makeStep(row, { verdict: 'blocked' })], row, { quiet })[0]

  it('sees a non-quiet blocked or warned step after a row, not a quiet or older one', () => {
    expect(hasAlarm([blocked(5)], 4)).toBe(true)
    expect(hasAlarm([blocked(5)], 5)).toBe(false)
    expect(hasAlarm([blocked(5, true)], 4)).toBe(false)
    expect(hasAlarm(place([makeStep(9, { verdict: 'warned' })], 9), 8)).toBe(true)
  })

  it('jumps on the first call', () => {
    expect(decideMove(null, { lastRow: 3, alarm: false }, true)).toBe('jump')
  })

  it('jumps, not slides, for the first steps after an empty drawing (page load, New session)', () => {
    expect(decideMove({ lastRow: -1 }, { lastRow: 9, alarm: false }, true)).toBe('jump')
    expect(decideMove({ lastRow: -1 }, { lastRow: 9, alarm: true }, false)).toBe('jump')
  })

  it('does nothing for an unchanged poll', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 3, alarm: false }, true)).toBe('none')
    expect(decideMove({ lastRow: 3 }, { lastRow: 3, alarm: false }, false)).toBe('none')
  })

  it('slides once when the newest row advances and the viewer is following', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 13, alarm: false }, true)).toBe('slide')
  })

  it('does not move a paused viewer, but a blocked or warned step resumes following', () => {
    expect(decideMove({ lastRow: 3 }, { lastRow: 4, alarm: false }, false)).toBe('none')
    expect(decideMove({ lastRow: 3 }, { lastRow: 4, alarm: true }, false)).toBe('slide')
  })
})

describe('movedFrom', () => {
  const rest = { x: 0, y: -500, zoom: 1 }
  it('counts any user event when no rest is known', () => {
    expect(movedFrom(null, rest)).toBe(true)
  })
  it('ignores no movement and a drift within the click slop', () => {
    expect(movedFrom(rest, rest)).toBe(false)
    expect(movedFrom(rest, { ...rest, y: rest.y + CLICK_SLOP })).toBe(false)
  })
  it('counts a move past the slop on either axis, or a zoom change', () => {
    expect(movedFrom(rest, { ...rest, y: rest.y - CLICK_SLOP - 1 })).toBe(true)
    expect(movedFrom(rest, { ...rest, x: CLICK_SLOP + 1 })).toBe(true)
    expect(movedFrom(rest, { ...rest, zoom: 0.9 })).toBe(true)
  })
})

describe('slideOptions', () => {
  it('uses a linear interpolation so the zoom never dips, and 400 ms', () => {
    expect(slideOptions((n) => n)).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
    expect(SLIDE_MS).toBeLessThanOrEqual(400)
  })
  it('is instant under reduced motion', () => {
    expect(slideOptions(() => 0).duration).toBe(0)
  })
  it('eases from 0 to 1', () => {
    expect(easeOutCubic(0)).toBe(0)
    expect(easeOutCubic(1)).toBe(1)
  })
})

describe('gestureStep', () => {
  const run = (g: Gesture, ...events: Parameters<typeof gestureStep>[1][]) =>
    events.reduce((acc, e) => {
      const out = gestureStep(acc.next, e)
      return { next: out.next, reissue: out.reissue }
    }, { next: g, reissue: false })

  it('a click with no movement does not pause following and asks for a slide to the target', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: true }, { type: 'end', user: true })
    expect(out.next.following).toBe(true)
    expect(out.reissue).toBe(true)
  })

  it('a real move pauses following and does not ask for a slide', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: true }, { type: 'move', user: true }, { type: 'end', user: true })
    expect(out.next.following).toBe(false)
    expect(out.reissue).toBe(false)
  })

  it('a programmatic move never pauses following or asks for a slide', () => {
    const out = run(INITIAL_GESTURE, { type: 'start', user: false }, { type: 'move', user: false }, { type: 'end', user: false })
    expect(out.next.following).toBe(true)
    expect(out.reissue).toBe(false)
  })

  it('resume sets following again', () => {
    const paused = run(INITIAL_GESTURE, { type: 'move', user: true }).next
    expect(paused.following).toBe(false)
    expect(gestureStep(paused, { type: 'resume' }).next.following).toBe(true)
  })

  it('a click while paused asks for nothing', () => {
    const paused = run(INITIAL_GESTURE, { type: 'move', user: true }, { type: 'end', user: true }).next
    expect(run(paused, { type: 'start', user: true }, { type: 'end', user: true }).reissue).toBe(false)
  })
})

describe('the newest step stays in view as polls arrive (real-sized orders)', () => {
  const view = (state: WindowState, pane: { width: number; height: number }): boolean => {
    const rows = rowsOf(state.steps)
    const vp = followTarget(rows, pane)
    const layout = layoutGraph(state.steps)
    const newest = state.steps.at(-1)
    const box = layout.nodes.find((n) => n.id === stepId(newest?.order ?? -1))
    if (box === undefined) return false
    const top = box.position.y * vp.zoom + vp.y
    const bottom = top + (box.height ?? 0) * vp.zoom
    const left = box.position.x * vp.zoom + vp.x
    const right = left + (box.width ?? 0) * vp.zoom
    return top >= 0 && bottom <= pane.height && left >= 0 && right <= pane.width
  }
  const polls = [40000, 40005, 40010, 40020, 40030, 40040].map((n) => stepsFrom(n, 10))

  it.each([PANE, { width: 644, height: 1080 }, { width: 960, height: 600 }])('in a %j pane through 50 steps', (pane) => {
    let state = initialWindowState()
    for (const steps of polls) {
      state = windowReducer(state, { type: 'snapshot', session: 's', steps })
      expect(view(state, pane), `after orders up to ${state.steps.at(-1)?.order}`).toBe(true)
    }
    expect(state.steps).toHaveLength(20)
  })
})

describe('rowsOf', () => {
  it('is empty for no steps and spans first to last otherwise', () => {
    expect(rowsOf([])).toEqual({ first: 0, last: -1 })
    expect(rowsOf(place(stepsFrom(1, 3), 7))).toEqual({ first: 7, last: 9 })
  })
})
