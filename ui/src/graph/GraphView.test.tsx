import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Viewport } from '@xyflow/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SLIDE_MS, easeOutCubic, followTarget, panExtent, rowsOf } from './camera'
import { GraphView } from './GraphView'
import { layoutGraph } from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep, place, stepsFrom } from './testing'

const spy = vi.hoisted(() => ({
  calls: [] as { vp: Viewport; options: Record<string, unknown> | undefined }[],
  props: {} as Record<string, any>,
  rf: undefined as any,
}))

vi.mock('@xyflow/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@xyflow/react')>()
  const { createElement } = await import('react')
  return {
    ...actual,
    useReactFlow: () => {
      const rf = actual.useReactFlow()
      spy.rf = rf
      return {
        ...rf,
        setViewport: (vp: Viewport, options?: Record<string, unknown>) => {
          spy.calls.push({ vp, options })
          return rf.setViewport(vp, options)
        },
      }
    },
    ReactFlow: (props: Record<string, any>) => {
      spy.props = props
      // ReactFlow is a forwardRef component object, not a function: render it.
      return createElement(actual.ReactFlow as never, props)
    },
  }
})

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

const viewportTransform = (container: HTMLElement) =>
  (container.querySelector('.react-flow__viewport') as HTMLElement).style.transform

const view = (steps: ReturnType<typeof place>, epoch = 0) => <GraphView steps={steps} epoch={epoch} />

beforeEach(() => {
  spy.calls.length = 0
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('drawing', () => {
  it('draws the demo story with labels that do not depend on colour', async () => {
    const steps = place(MOCK_STEPS)
    const { container } = render(view(steps))
    await settle()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('SECRET')).toBeTruthy()
    expect(screen.getByText('R1')).toBeTruthy()
    expect(screen.getByText('ntfy.sh')).toBeTruthy()
    const count = (selector: string, text: string) =>
      [...container.querySelectorAll(selector)].filter((n) => n.textContent?.includes(text)).length
    expect(count('.react-flow__node-file', 'README.md')).toBe(1)
    expect(count('.react-flow__node-step', 'README.md')).toBe(2)
    expect(count('.react-flow__node-file', '.env')).toBe(1)
    expect(count('.react-flow__node-step', '.env')).toBe(1)
    expect(screen.getAllByText('SECRET')).toHaveLength(1)
    expect(container.querySelectorAll('.react-flow__node')).toHaveLength(layoutGraph(steps).nodes.length)
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
  })

  it('shows a read step file path cut at the left end, with the full path in title', async () => {
    const path = 'src/very/long/directory/path/to/a-file-name.ts'
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: path, command: null })])))
    await settle()
    expect(container.querySelector(`[title="1: read ${path}"]`)).not.toBeNull()
    const bdi = container.querySelector('.react-flow__node-step bdi')
    expect(bdi?.textContent).toBe(path)
    expect(bdi?.closest('[dir="rtl"]')).not.toBeNull()
  })

  it('shows a hostile file path as literal text on a read step', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: hostile, command: null })])))
    await settle()
    expect(screen.getAllByText(hostile).length).toBeGreaterThanOrEqual(1)
    expect(container.querySelector('img')).toBeNull()
  })

  it('a read step with no file renders without stray text or throwing', async () => {
    const { container } = render(view(place([makeStep(1, { kind: 'read', file: null, command: null })])))
    await settle()
    expect(container.querySelector('.react-flow__node-step')?.textContent).toBe('read')
  })

  it('labels a warned step WARN', async () => {
    render(view(place([makeStep(1, { verdict: 'warned', rule: 'R1', host: 'x.com', command: 'curl x.com' })])))
    await settle()
    expect(screen.getByText('WARN')).toBeTruthy()
    expect(screen.queryByText('BLOCKED')).toBeNull()
  })

  it('keeps every edge after React Flow measures and after a poll rebuilds the node objects', async () => {
    const steps = place(MOCK_STEPS)
    const { container, rerender } = render(view(steps))
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
    rerender(view(steps.map((s) => ({ ...s }))))
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(steps).edges.length)
  })

  it('shows server text literally, never as HTML', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(view(place([makeStep(1, { command: hostile })])))
    await settle()
    expect(screen.getByText(hostile)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('lets node tooltips fire: pointer events on and the full text in title', async () => {
    const long = `curl -d ${'x'.repeat(80)} very-long-host.example.com`
    const { container } = render(view(place([makeStep(40001, { command: long })])))
    await settle()
    expect((container.querySelector('.react-flow__node') as HTMLElement).style.pointerEvents).toBe('all')
    expect(container.querySelector(`[title*="${long}"]`)).not.toBeNull()
  })
})

describe('camera', () => {
  it('puts the camera at the top with few steps and follows the newest with many', async () => {
    const few = render(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(viewportTransform(few.container)).toBe('translate(0px,96px) scale(1)')
    few.unmount()
    const many = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(many.container)).toBe('translate(0px,-64px) scale(1)')
  })

  it('works with absolute rows far from 0', async () => {
    const { container } = render(view(place(stepsFrom(40000, 20), 40000)))
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
    expect(container.querySelectorAll('.react-flow__node').length).toBeGreaterThan(0)
  })

  it('never produces NaN for an unmeasured 0x0 pane', async () => {
    const { container } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
  })

  it('recomputes the camera, with a jump, when the pane is resized after mount', async () => {
    let paneHeight = 1080
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') {
        return { width: 960, height: paneHeight, x: 0, y: 0, top: 0, left: 0, right: 960, bottom: paneHeight, toJSON() {} }
      }
      return real.call(this)
    })
    const { container } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-64px) scale(1)')
    spy.calls.length = 0
    paneHeight = 700
    await act(async () => {
      globalThis.fireResizeObservers()
    })
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-444px) scale(1)')
    expect(spy.calls.at(-1)?.options).toBeUndefined()
  })

  it('scales the drawing to fit a 644-wide pane', async () => {
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') {
        return { width: 644, height: 1080, x: 0, y: 0, top: 0, left: 0, right: 644, bottom: 1080, toJSON() {} }
      }
      return real.call(this)
    })
    const { container } = render(view(place(stepsFrom(40000, 5))))
    await settle()
    expect(viewportTransform(container)).toContain('scale(0.69')
  })

  it('jumps (no options) on first paint and on an epoch change', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(spy.calls.at(-1)?.options).toBeUndefined()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(1, 2)), 1))
    await settle()
    expect(spy.calls.length).toBeGreaterThan(0)
    expect(spy.calls.every((c) => c.options === undefined)).toBe(true)
  })

  it('slides once with exactly the agreed options when a step arrives', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 4))))
    await settle()
    expect(spy.calls).toHaveLength(1)
    expect(spy.calls[0].options).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
  })

  it('does not move the camera for an unchanged poll', async () => {
    const steps = place(stepsFrom(40000, 3))
    const { rerender } = render(view(steps))
    await settle()
    spy.calls.length = 0
    rerender(view(steps))
    rerender(view(place(stepsFrom(40000, 3))))
    await settle()
    expect(spy.calls).toHaveLength(0)
  })

  it('slides once for a burst of ten steps', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 5))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 15))))
    await settle()
    expect(spy.calls).toHaveLength(1)
  })

  it('slides instantly under reduced motion', async () => {
    globalThis.setReducedMotion(true)
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40000, 4))))
    await settle()
    expect(spy.calls[0].options?.duration).toBe(0)
  })
})

describe('pan, zoom and Follow', () => {
  const userMove = () =>
    act(() => {
      spy.props.onMove(new MouseEvent('mousemove'), { x: 0, y: 0, zoom: 1 })
    })

  it('locks zoom, allows only vertical pan, and does not cull offscreen elements', async () => {
    const steps = place(stepsFrom(40000, 20))
    render(view(steps))
    await settle()
    const p = spy.props
    expect(p.zoomOnScroll).toBe(false)
    expect(p.zoomOnPinch).toBe(false)
    expect(p.zoomOnDoubleClick).toBe(false)
    expect(p.minZoom).toBe(p.maxZoom)
    expect(p.panOnDrag).toBe(true)
    expect(p.panOnScroll).toBe(true)
    expect(p.panOnScrollMode).toBe('vertical')
    expect(p.onlyRenderVisibleElements).toBeUndefined()
    expect(p.viewport).toBeUndefined()
    expect(p.translateExtent).toEqual(panExtent(rowsOf(steps), { width: 0, height: 0 }))
  })

  it('shows Follow only after a user move, not after a programmatic one', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    act(() => spy.props.onMove(null, { x: 0, y: 0, zoom: 1 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    userMove()
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('a paused viewer is not moved by a new step; clicking Follow slides back once', async () => {
    const { rerender } = render(view(place(stepsFrom(40000, 20))))
    await settle()
    userMove()
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40001, 20), 1)))
    await settle()
    expect(spy.calls.every((c) => c.options === undefined)).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Follow' }))
    const slides = spy.calls.filter((c) => c.options !== undefined)
    expect(slides).toHaveLength(1)
    expect(slides[0].vp).toEqual(followTarget(rowsOf(place(stepsFrom(40001, 20), 1)), { width: 0, height: 0 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
  })

  it('a blocked step resumes following with one slide, but a quiet one does not', async () => {
    const base = place(stepsFrom(40000, 20))
    const { rerender } = render(view(base))
    await settle()
    userMove()
    const blocked = place([makeStep(40020, { verdict: 'blocked', rule: 'R1', host: 'x.com' })], 20)
    spy.calls.length = 0
    rerender(view([...base.slice(1), ...blocked.map((s) => ({ ...s, quiet: true }))]))
    await settle()
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
    rerender(view([...base.slice(2), ...blocked, ...place([makeStep(40021, { verdict: 'blocked' })], 21)]))
    await settle()
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    expect(spy.calls.filter((c) => c.options !== undefined)).toHaveLength(1)
  })

  it('a click with no movement does not pause following and slides to the target if the camera is off it', async () => {
    const steps = place(stepsFrom(40000, 4))
    const { rerender } = render(view(place(stepsFrom(40000, 3))))
    await settle()
    rerender(view(steps))
    await act(async () => {
      await spy.rf.setViewport({ x: 0, y: -1, zoom: 1 })
    })
    spy.calls.length = 0
    act(() => spy.props.onMoveStart(new MouseEvent('mousedown'), { x: 0, y: 0, zoom: 1 }))
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: 0, zoom: 1 }))
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull()
    expect(spy.calls).toHaveLength(1)
    expect(spy.calls[0].options).toEqual({ duration: SLIDE_MS, ease: easeOutCubic, interpolate: 'linear' })
    expect(spy.calls[0].vp).toEqual(followTarget(rowsOf(steps), { width: 0, height: 0 }))
  })

  it('a click when the camera is already on the target does nothing', async () => {
    render(view(place(stepsFrom(40000, 3))))
    await settle()
    spy.calls.length = 0
    act(() => spy.props.onMoveStart(new MouseEvent('mousedown'), { x: 0, y: 0, zoom: 1 }))
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: 0, zoom: 1 }))
    expect(spy.calls).toHaveLength(0)
  })

  it('a single wheel notch pauses following, since React Flow reports only a start for it', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    act(() => spy.props.onMoveStart(new WheelEvent('wheel'), { x: 0, y: 0, zoom: 1 }))
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('does not resume following when the viewer pans back to the newest row by hand', async () => {
    render(view(place(stepsFrom(40000, 20))))
    await settle()
    userMove()
    act(() => spy.props.onMoveEnd(new MouseEvent('mouseup'), { x: 0, y: -64, zoom: 1 }))
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy()
  })

  it('clamps a paused viewer in place, with no easing, when the window slides', async () => {
    const first = place(stepsFrom(40000, 20), 100)
    const { rerender } = render(view(first))
    await settle()
    userMove()
    await act(async () => {
      await spy.rf.setViewport({ x: 0, y: -(90 * 56), zoom: 1 })
    })
    spy.calls.length = 0
    rerender(view(place(stepsFrom(40010, 20), 110)))
    await settle()
    const last = spy.calls.at(-1)
    expect(last?.options).toBeUndefined()
    const extent = panExtent({ first: 110, last: 129 }, { width: 0, height: 0 })
    expect(-last!.vp.y).toBeGreaterThanOrEqual(extent[0][1])
  })
})
