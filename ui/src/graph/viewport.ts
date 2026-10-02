import type { Viewport } from '@xyflow/react'
import { BOTTOM_PAD, CONTENT_W, ROW_PITCH, TOP_PAD } from './layout'

export interface PaneSize {
  width: number
  height: number
}

/** The 960x1080 half screen the page is designed for. */
export const FALLBACK_PANE: PaneSize = { width: 960, height: 1080 }

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

/**
 * Where to put the camera: zoom 1 always. Vertically, keep the newest row's
 * bottom at the pane's bottom padding once rows outgrow the pane. Horizontally,
 * a pane narrower than the content shifts left so the rules lane stays visible
 * (the step column clips instead).
 */
export function computeViewport(rowCount: number, pane: PaneSize): Viewport {
  const { width, height } = resolvePane(pane)
  const y = Math.min(TOP_PAD, height - BOTTOM_PAD - rowCount * ROW_PITCH)
  const x = Math.min(0, width - CONTENT_W)
  return { x, y, zoom: 1 }
}
