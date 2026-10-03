import { useCallback, useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

// One MediaQueryList and one change listener for the whole page, however many
// boxes and edges read it. `undefined` until first asked; null without matchMedia.
let media: MediaQueryList | null | undefined
const listeners = new Set<() => void>()

function query(): MediaQueryList | null {
  if (media === undefined) media = typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null
  return media
}

function notify(): void {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  const list = query()
  if (list === null) return () => {}
  if (listeners.size === 0) list.addEventListener('change', notify)
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) list.removeEventListener('change', notify)
  }
}

function snapshot(): boolean {
  return query()?.matches ?? false
}

/** Our own hook: motion's MotionConfig keeps opacity animations, which is not "every change instant". */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

/** `ms(n)` is n, or 0 under reduced motion. Every duration and delay goes through it. */
export function useMs(): (n: number) => number {
  return useMotionPolicy().ms
}

/** Both at once, for components that need the flag and `ms`: one subscription, not two. */
export function useMotionPolicy(): { reduced: boolean; ms: (n: number) => number } {
  const reduced = useReducedMotion()
  const ms = useCallback((n: number) => (reduced ? 0 : n), [reduced])
  return { reduced, ms }
}
