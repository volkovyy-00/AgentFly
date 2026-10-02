import { useLayoutEffect, useRef, useState, type RefObject } from 'react'
import type { PaneSize } from './camera'

/** Measures an element. 0x0 until measured; resolvePane falls back to 960x1080. */
export function usePaneSize(): { ref: RefObject<HTMLDivElement | null>; pane: PaneSize } {
  const ref = useRef<HTMLDivElement | null>(null)
  const [pane, setPane] = useState<PaneSize>({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const element = ref.current
    if (element === null) return
    function measure(): void {
      const rect = element!.getBoundingClientRect()
      setPane((p) => (p.width === rect.width && p.height === rect.height ? p : { width: rect.width, height: rect.height }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, pane }
}
