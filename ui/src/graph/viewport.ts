import type { Viewport } from '@xyflow/react'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD } from './layout'

export interface PaneSize {
  width: number
  height: number
}

/** The 960x1080 half screen the page is designed for. */
export const FALLBACK_PANE: PaneSize = { width: 960, height: 1080 }

/** Floor for fit-to-width zoom; below this the step column may clip on the left. */
export const MIN_ZOOM = 0.5

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

/**
 * Where to put the camera. Zoom is at most 1; a pane narrower than the content
 * scales down (floor MIN_ZOOM) so the drawing fits. Vertically, keep the newest
 * row's bottom at the pane's bottom padding once rows outgrow the pane.
 * TOP_PAD and BOTTOM_PAD are in screen pixels.
 */
export function computeViewport(rowCount: number, pane: PaneSize): Viewport {
  const { width, height } = resolvePane(pane)
  const zoom = clamp(width / CONTENT_W, MIN_ZOOM, 1)
  const y = Math.min(TOP_PAD, height - BOTTOM_PAD - rowCount * ROW_PITCH * zoom)
  const x = Math.min(0, width - CONTENT_W * zoom)
  return { x, y, zoom }
}
