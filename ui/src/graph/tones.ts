/**
 * Every colour pair on the page, as data. Components render only `classes`, so
 * the test can iterate this table: there is nothing to scan for pairings.
 * Values are token names; the hex lives in index.css. Muted text is only for
 * canvas or surface: on the tinted fills it fails 7:1.
 */
export interface Tone {
  bg: string
  text: string
  border: string | null
  classes: string
}

const tone = (bg: string, text: string, border: string | null, classes: string): Tone => ({ bg, text, border, classes })

export const TONES = {
  app: tone('canvas', 'ink', null, 'bg-canvas text-ink'),
  empty: tone('canvas', 'muted', null, 'bg-canvas text-muted'),
  step: tone('fill-step', 'ink', 'aux', 'bg-fill-step text-ink border-aux'),
  // The bright alarm border is drawn by the wipe overlay (DECOR), over this neutral one.
  stepBlocked: tone('fill-blocked', 'ink', 'aux', 'bg-fill-blocked text-ink border-aux'),
  stepWarned: tone('fill-warned', 'ink', 'aux', 'bg-fill-warned text-ink border-aux'),
  // File and host fills carry a bright border of the same hue (spec section 7).
  file: tone('fill-link', 'ink', 'link', 'bg-fill-link text-ink border-link'),
  fileSecret: tone('fill-secret', 'canvas', null, 'bg-fill-secret text-canvas'),
  host: tone('fill-link', 'ink', 'link', 'bg-fill-link text-ink border-link'),
  rule: tone('fill-blocked', 'ink', 'blocked', 'bg-fill-blocked text-ink border-blocked'),
  chipBlocked: tone('chip-blocked', 'canvas', null, 'bg-chip-blocked text-canvas'),
  chipWarned: tone('chip-warned', 'canvas', null, 'bg-chip-warned text-canvas'),
  chipSecret: tone('fill-secret', 'canvas', null, 'bg-fill-secret text-canvas'),
  banner: tone('fill-blocked', 'ink', null, 'bg-fill-blocked text-ink'),
  button: tone('surface', 'ink', 'ink', 'bg-surface text-ink border-ink'),
} as const satisfies Record<string, Tone>

/** Shape shared by the New session and Follow buttons (each adds its own position). */
export const BUTTON_CLASSES = `z-30 rounded border-2 px-3 text-base leading-6 font-semibold ${TONES.button.classes}`

/** Decorations that carry no text: borders, rings, flashes. `token` is checked at 3:1 on canvas. */
export const DECOR = {
  wipeBlocked: { token: 'blocked', classes: 'border-blocked' },
  wipeWarned: { token: 'warned', classes: 'border-warned' },
  // The OFFLINE banner's text pair is a quiet 7:1 fill; this bright stripe along its bottom edge is what reads as red from across a room.
  bannerStripe: { token: 'blocked', classes: 'border-blocked' },
  ring: { token: 'secret', classes: 'border-secret' },
  flash: { token: null, classes: 'bg-ink' },
} as const
