import { useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { KEY_STEP_PX, type Layout } from './cardPrefs'

interface SplitterProps {
  layout: Layout
  /** Current card size along the split axis, px. */
  size: number
  min: number
  max: number
  /** Live size while dragging or on a key press. */
  onResize: (px: number) => void
  /** The size to remember (px), or null to go back to the default. */
  onCommit: (px: number | null) => void
}

const clamp = (n: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, n))

/**
 * The divider between the trail and the Why card. The card is below (stacked) or to
 * the right (side by side), so dragging up or left grows it. Arrow keys resize in
 * 24 px steps, a double-click resets to the default.
 */
export function Splitter({ layout, size, min, max, onResize, onCommit }: SplitterProps) {
  const drag = useRef<{ start: number; startSize: number; last: number } | null>(null)
  const stacked = layout === 'stacked'

  function onPointerDown(e: PointerEvent<HTMLDivElement>): void {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const start = stacked ? e.clientY : e.clientX
    drag.current = { start, startSize: size, last: size }
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>): void {
    const d = drag.current
    if (d === null) return
    const pos = stacked ? e.clientY : e.clientX
    d.last = clamp(d.startSize + (d.start - pos), min, max)
    onResize(d.last)
  }

  function endDrag(): void {
    const d = drag.current
    drag.current = null
    if (d !== null) onCommit(d.last)
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>): void {
    const grow = stacked ? 'ArrowUp' : 'ArrowLeft'
    const shrink = stacked ? 'ArrowDown' : 'ArrowRight'
    if (e.key !== grow && e.key !== shrink) return
    e.preventDefault()
    const next = clamp(size + (e.key === grow ? KEY_STEP_PX : -KEY_STEP_PX), min, max)
    onResize(next)
    onCommit(next)
  }

  return (
    <div
      className="tr-split"
      role="separator"
      tabIndex={0}
      aria-label="Resize the Why card"
      aria-orientation={stacked ? 'horizontal' : 'vertical'}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={size}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => onCommit(null)}
    >
      <span className="tr-grip" aria-hidden="true" />
    </div>
  )
}
