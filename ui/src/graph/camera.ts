import type { CoordinateExtent, Viewport } from '@xyflow/react'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD } from './layout'
import type { PlacedStep } from './types'

export interface PaneSize {
  width: number
  height: number
}

/** The 960x1080 half screen the page is designed for. */
export const FALLBACK_PANE: PaneSize = { width: 960, height: 1080 }

/** Floor for fit-to-width zoom; below this the step column may clip on the left. */
export const MIN_ZOOM = 0.5

export const SLIDE_MS = 400

export const easeOutCubic = (t: number): number => 1 - (1 - t) ** 3

function usable(n: number): boolean {
  return Number.isFinite(n) && n > 0
}

/** Replace an unmeasured (0x0, NaN) pane with the design size. */
export function resolvePane(pane: PaneSize): PaneSize {
  return {
    width: usable(pane.width) ? pane.width : FALLBACK_PANE.width,
    height: usable(pane.height) ? pane.height : FALLBACK_PANE.height,
  }
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n))
}

/** The one zoom the camera ever uses; min and max zoom are both set to it. */
export function zoomFor(width: number): number {
  return clamp(width / CONTENT_W, MIN_ZOOM, 1)
}

/** First and last drawn row, inclusive. `last < first` when nothing is drawn. */
export interface Rows {
  first: number
  last: number
}

/**
 * `groupRowCount` is the rows the group takes above the oldest window row (the
 * summary plus the drawn flagged steps; 0 for no group), so the pan range and
 * the follow target treat the summary row as the first row.
 */
export function rowsOf(steps: readonly PlacedStep[], groupRowCount = 0): Rows {
  const first = steps[0]
  const last = steps.at(-1)
  if (first === undefined || last === undefined) return { first: 0, last: -1 }
  return { first: first.row - groupRowCount, last: last.row }
}

/**
 * Where the camera sits while following: the newest row's bottom `BOTTOM_PAD`
 * above the pane bottom, but never so low that the first drawn row passes
 * `TOP_PAD`. Both pads are screen pixels.
 */
export function followTarget(rows: Rows, pane: PaneSize): Viewport {
  const { width, height } = resolvePane(pane)
  const zoom = zoomFor(width)
  const fromTop = TOP_PAD - rows.first * ROW_PITCH * zoom
  const fromBottom = height - BOTTOM_PAD - (rows.last + 1) * ROW_PITCH * zoom
  return { x: Math.min(0, width - CONTENT_W * zoom), y: Math.min(fromTop, fromBottom), zoom }
}

/**
 * The pan range in flow units: the drawn rows plus the pads (divided by zoom,
 * since the pads are screen pixels), and never shorter than the pane (d3
 * centres content that is shorter). The x range is exactly the visible width,
 * so there is nothing to pan sideways.
 */
export function panExtent(rows: Rows, pane: PaneSize): CoordinateExtent {
  const { width, height } = resolvePane(pane)
  const zoom = zoomFor(width)
  const target = followTarget(rows, pane)
  const x0 = -target.x / zoom + 0
  const top = rows.first * ROW_PITCH - TOP_PAD / zoom
  const bottom = Math.max((rows.last + 1) * ROW_PITCH + BOTTOM_PAD / zoom, top + height / zoom)
  return [
    [x0, top],
    [x0 + width / zoom, bottom],
  ]
}

/** React Flow never re-clamps an existing viewport, so we do it. Returns `vp` itself when nothing changes. */
export function clampViewport(vp: Viewport, extent: CoordinateExtent, pane: PaneSize): Viewport {
  const { height } = resolvePane(pane)
  const [[, top], [, bottom]] = extent
  const visibleTop = -vp.y / vp.zoom
  const lowest = Math.max(top, bottom - height / vp.zoom)
  const clamped = Math.min(lowest, Math.max(top, visibleTop))
  return clamped === visibleTop ? vp : { ...vp, y: -clamped * vp.zoom + 0 }
}

/** A blocked or warned step that is newer than `afterRow` and not from the first paint. */
export function hasAlarm(steps: readonly PlacedStep[], afterRow: number): boolean {
  return steps.some((s) => s.row > afterRow && !s.quiet && (s.verdict === 'blocked' || s.verdict === 'warned'))
}

export type Move = 'none' | 'jump' | 'slide'

/**
 * What the camera does after a render. `prev` is null on the first call. The
 * first steps after an empty drawing (`lastRow` -1: the page's empty mount, or
 * the remount after New session) are a first paint too, so they jump. Any move
 * (a jump, or a slide, including an alarm's slide from a paused viewer) leaves
 * the viewer following.
 */
export function decideMove(
  prev: { lastRow: number } | null,
  next: { lastRow: number; alarm: boolean },
  following: boolean,
): Move {
  if (prev === null || prev.lastRow < 0) return 'jump'
  if (next.lastRow === prev.lastRow) return 'none'
  if (next.alarm) return 'slide'
  return following ? 'slide' : 'none'
}

/** Options for every slide. `linear` keeps the zoom locked; the default interpolation dips it mid-flight. */
export function slideOptions(ms: (n: number) => number): {
  duration: number
  ease: (t: number) => number
  interpolate: 'linear'
} {
  return { duration: ms(SLIDE_MS), ease: easeOutCubic, interpolate: 'linear' }
}

export interface Gesture {
  following: boolean
  /** True once a user move (not just a mousedown) happened in this gesture. */
  moved: boolean
}

export const INITIAL_GESTURE: Gesture = { following: true, moved: false }

/** Screen pixels a click may drift without counting as a pan. */
export const CLICK_SLOP = 3

/**
 * Whether a user event really moved the camera away from where it last rested.
 * React Flow reports a wheel or drag even when the extent clamps it to nothing
 * (a wheel down at the newest row, a sideways swipe, a short session), and a
 * click may drift a pixel; none of these is the viewer scrolling away. With no
 * rest known yet, any user event counts.
 */
export function movedFrom(rest: Viewport | null, now: Viewport): boolean {
  if (rest === null) return true
  return Math.abs(now.x - rest.x) > CLICK_SLOP || Math.abs(now.y - rest.y) > CLICK_SLOP || now.zoom !== rest.zoom
}

export type GestureEvent =
  | { type: 'resume' }
  | { type: 'start'; user: boolean }
  | { type: 'move'; user: boolean }
  | { type: 'end'; user: boolean }

/**
 * d3 interrupts a running slide and reports a start on mousedown, before any
 * movement, so only a user `move` pauses following. A click with no movement
 * while following asks the caller to slide to the current follow target. It
 * does not rely on remembering the interrupted slide: React Flow reports the
 * end up to 150 ms late, so a slow click would find that memory already gone.
 */
export function gestureStep(g: Gesture, e: GestureEvent): { next: Gesture; reissue: boolean } {
  switch (e.type) {
    case 'resume':
      return { next: { ...g, following: true }, reissue: false }
    case 'start':
      return { next: e.user ? { ...g, moved: false } : g, reissue: false }
    case 'move':
      return e.user ? { next: { ...g, following: false, moved: true }, reissue: false } : { next: g, reissue: false }
    case 'end':
      if (!e.user) return { next: g, reissue: false }
      return { next: { ...g, moved: false }, reissue: !g.moved && g.following }
  }
}
