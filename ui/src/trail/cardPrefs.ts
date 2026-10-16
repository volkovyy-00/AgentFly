/** Below this pane width the trail is on top and the Why card below (the half-screen layout, the main one). */
const STACK_BELOW_PX = 1080

export type Layout = 'stacked' | 'side'

export const layoutOf = (paneWidth: number): Layout => (paneWidth < STACK_BELOW_PX ? 'stacked' : 'side')

export const CARD_PREFS_KEY = 'agentfly_trail_card'

/** The Why card's remembered state. A null size means "the default for this layout". */
export interface CardPrefs {
  hidden: boolean
  /** Card height in px when stacked. */
  stacked: number | null
  /** Card width in px when side by side. */
  side: number | null
}

export const DEFAULT_PREFS: CardPrefs = { hidden: false, stacked: null, side: null }

/** Card limits. The trail keeps at least a quarter of the pane and at least 300 px (the pinned strip and toolbar take about 160 of them). */
const MIN_CARD_HEIGHT = 160
const MIN_CARD_WIDTH = 280
const MIN_TRAIL_SHARE = 0.25
const MIN_TRAIL_PX = 300
/** Size used before the pane has been measured. */
const UNMEASURED_CARD_PX = 280
/** Arrow-key step on the splitter. */
export const KEY_STEP_PX = 24
/** The hide bar's thickness (stacked: height, side: width). */
export const HIDE_BAR_PX = 40

function sizeOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

export function readPrefs(): CardPrefs {
  try {
    const raw = window.localStorage.getItem(CARD_PREFS_KEY)
    if (raw === null) return DEFAULT_PREFS
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_PREFS
    const r = parsed as Record<string, unknown>
    return { hidden: r.hidden === true, stacked: sizeOrNull(r.stacked), side: sizeOrNull(r.side) }
  } catch {
    return DEFAULT_PREFS
  }
}

export function writePrefs(prefs: CardPrefs): void {
  try {
    window.localStorage.setItem(CARD_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    // Storage blocked: the card keeps its state until reload, which is fine.
  }
}

/** [min, max] card size along the split axis for a pane of `extent` px (0 = not measured). */
export function cardBounds(layout: Layout, extent: number): readonly [number, number] {
  const min = layout === 'stacked' ? MIN_CARD_HEIGHT : MIN_CARD_WIDTH
  if (extent <= 0) return [min, Math.max(min, UNMEASURED_CARD_PX)]
  const trail = Math.max(extent * MIN_TRAIL_SHARE, MIN_TRAIL_PX)
  return [min, Math.max(min, Math.floor(extent - trail))]
}

/** The default size: 46% of the height when stacked; a third of the width, 380 to 480 px, side by side. */
export function defaultCardSize(layout: Layout, extent: number): number {
  if (extent <= 0) return UNMEASURED_CARD_PX
  if (layout === 'stacked') return Math.round(extent * 0.46)
  return Math.min(480, Math.max(380, Math.round(extent / 3)))
}

/** The size to draw: the remembered one (or the default), kept inside the bounds. */
export function resolveCardSize(layout: Layout, extent: number, remembered: number | null): number {
  const [min, max] = cardBounds(layout, extent)
  const wanted = remembered ?? defaultCardSize(layout, extent)
  return Math.min(max, Math.max(min, Math.round(wanted)))
}
