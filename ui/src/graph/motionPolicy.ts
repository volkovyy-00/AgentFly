import { useCallback, useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(listener: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {}
  const media = window.matchMedia(QUERY)
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}

function snapshot(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches
}

/** Our own hook: motion's MotionConfig keeps opacity animations, which is not "every change instant". */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

/** `ms(n)` is n, or 0 under reduced motion. Every duration and delay goes through it. */
export function useMs(): (n: number) => number {
  const reduced = useReducedMotion()
  return useCallback((n: number) => (reduced ? 0 : n), [reduced])
}
