// jsdom has no layout. These stubs make React Flow measure nodes the way a
// browser does: ResizeObserver fires after observe(), nodes report an
// offsetWidth/offsetHeight, and the handles React Flow finds in the DOM replace
// the `handles` data on the node. A no-op ResizeObserver stub would skip that
// step and hide a node that forgot to render its <Handle>.

class FiringResizeObserver {
  private readonly callback: ResizeObserverCallback
  private readonly targets = new Set<Element>()

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    resizeObservers.add(this)
  }

  observe(target: Element): void {
    this.targets.add(target)
    // Browsers deliver observations asynchronously, after layout.
    setTimeout(() => this.fire(), 0)
  }

  unobserve(target: Element): void {
    this.targets.delete(target)
  }

  disconnect(): void {
    this.targets.clear()
    resizeObservers.delete(this)
  }

  fire(): void {
    if (this.targets.size === 0) return
    const entries = [...this.targets].map(
      (target) => ({ target, contentRect: target.getBoundingClientRect() }) as ResizeObserverEntry,
    )
    this.callback(entries, this as unknown as ResizeObserver)
  }
}

const resizeObservers = new Set<FiringResizeObserver>()

declare global {
  // eslint-disable-next-line no-var
  var fireResizeObservers: () => void
}

/** Tests call this after changing a mocked element size. */
globalThis.fireResizeObservers = () => {
  for (const observer of resizeObservers) observer.fire()
}

class FakeDOMMatrixReadOnly {
  m22: number
  constructor(transform?: string) {
    const scale = /scale\(([\d.]+)\)/.exec(transform ?? '')
    this.m22 = scale ? Number(scale[1]) : 1
  }
}

globalThis.ResizeObserver = FiringResizeObserver as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly = FakeDOMMatrixReadOnly as unknown as typeof DOMMatrixReadOnly

function pixels(value: string): number {
  return Number.parseFloat(value) || 0
}

Object.defineProperties(HTMLElement.prototype, {
  offsetWidth: {
    configurable: true,
    get(this: HTMLElement) {
      return pixels(this.style.width)
    },
  },
  offsetHeight: {
    configurable: true,
    get(this: HTMLElement) {
      return pixels(this.style.height)
    },
  },
})
