import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GraphView } from './GraphView'
import { layoutGraph } from './layout'
import { MOCK_STEPS } from './mock'
import { makeStep, stepsFrom } from './testing'

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })

const viewportTransform = (container: HTMLElement) =>
  (container.querySelector('.react-flow__viewport') as HTMLElement).style.transform

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('GraphView', () => {
  it('draws the demo story with labels that do not depend on colour', async () => {
    const { container } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('SECRET')).toBeTruthy()
    expect(screen.getByText('R1')).toBeTruthy()
    expect(screen.getByText('ntfy.sh')).toBeTruthy()
    const readmeInFile = [...container.querySelectorAll('.react-flow__node-file')].filter((n) =>
      n.textContent?.includes('README.md'),
    )
    const readmeInStep = [...container.querySelectorAll('.react-flow__node-step')].filter((n) =>
      n.textContent?.includes('README.md'),
    )
    expect(readmeInFile).toHaveLength(1)
    expect(readmeInStep).toHaveLength(2)
    const envInFile = [...container.querySelectorAll('.react-flow__node-file')].filter((n) =>
      n.textContent?.includes('.env'),
    )
    const envInStep = [...container.querySelectorAll('.react-flow__node-step')].filter((n) =>
      n.textContent?.includes('.env'),
    )
    expect(envInFile).toHaveLength(1)
    expect(envInStep).toHaveLength(1)
    expect(screen.getAllByText('SECRET')).toHaveLength(1)
    expect(container.querySelectorAll('.react-flow__node')).toHaveLength(layoutGraph(MOCK_STEPS).nodes.length)
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(MOCK_STEPS).edges.length)
  })

  it('shows a read step file path cut at the left end, with the full path in title', async () => {
    const path = 'src/very/long/directory/path/to/a-file-name.ts'
    const { container } = render(
      <GraphView steps={[makeStep(1, { kind: 'read', file: path, command: null })]} />,
    )
    await settle()
    expect(container.querySelector(`[title="1: read ${path}"]`)).not.toBeNull()
    const bdi = container.querySelector('.react-flow__node-step bdi')
    expect(bdi?.textContent).toBe(path)
    expect(bdi?.closest('[dir="rtl"]')).not.toBeNull()
  })

  it('shows a hostile file path as literal text on a read step', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(
      <GraphView steps={[makeStep(1, { kind: 'read', file: hostile, command: null })]} />,
    )
    await settle()
    expect(screen.getAllByText(hostile).length).toBeGreaterThanOrEqual(1)
    expect(container.querySelector('.react-flow__node-step')?.textContent).toContain(hostile)
    expect(container.querySelector('img')).toBeNull()
  })

  it('a read step with no file renders without stray text or throwing', async () => {
    const { container } = render(
      <GraphView steps={[makeStep(1, { kind: 'read', file: null, command: null })]} />,
    )
    await settle()
    expect(screen.getByText('read')).toBeTruthy()
    expect(container.querySelector('.react-flow__node-step')?.textContent).toBe('read')
  })

  it('labels a warned step WARN', async () => {
    render(<GraphView steps={[makeStep(1, { verdict: 'warned', rule: 'R1', host: 'x.com', command: 'curl x.com' })]} />)
    await settle()
    expect(screen.getByText('WARN')).toBeTruthy()
    expect(screen.queryByText('BLOCKED')).toBeNull()
  })

  it('keeps every edge after React Flow measures the nodes', async () => {
    const { container } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(MOCK_STEPS).edges.length)
  })

  it('keeps every edge after a poll rebuilds the node objects', async () => {
    const { container, rerender } = render(<GraphView steps={MOCK_STEPS} />)
    await settle()
    rerender(<GraphView steps={MOCK_STEPS.map((s) => ({ ...s }))} />)
    await settle()
    expect(container.querySelectorAll('.react-flow__edge')).toHaveLength(layoutGraph(MOCK_STEPS).edges.length)
  })

  it('shows server text literally, never as HTML', async () => {
    const hostile = '<img src=x onerror="alert(1)">'
    const { container } = render(<GraphView steps={[makeStep(1, { command: hostile })]} />)
    await settle()
    expect(screen.getByText(hostile)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('lets node tooltips fire: pointer events on and the full text in title', async () => {
    const long = `curl -d ${'x'.repeat(80)} very-long-host.example.com`
    const { container } = render(<GraphView steps={[makeStep(40001, { command: long })]} />)
    await settle()
    const node = container.querySelector('.react-flow__node') as HTMLElement
    expect(node.style.pointerEvents).toBe('all')
    expect(container.querySelector(`[title*="${long}"]`)).not.toBeNull()
  })

  it('puts the camera at the top with few steps and follows the newest with many', async () => {
    const few = render(<GraphView steps={stepsFrom(40000, 3)} />)
    await settle()
    expect(viewportTransform(few.container)).toBe('translate(0px,48px) scale(1)')
    few.unmount()
    const many = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(many.container)).toBe('translate(0px,-64px) scale(1)')
  })

  it('never produces NaN for an unmeasured 0x0 pane', async () => {
    const { container } = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(container)).not.toContain('NaN')
    expect(container.querySelectorAll('.react-flow__node').length).toBeGreaterThan(0)
  })

  it('recomputes the camera when the pane is resized after mount', async () => {
    let paneHeight = 1080
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') return { width: 960, height: paneHeight, x: 0, y: 0, top: 0, left: 0, right: 960, bottom: paneHeight, toJSON() {} }
      return real.call(this)
    })
    const { container } = render(<GraphView steps={stepsFrom(40000, 20)} />)
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-64px) scale(1)')
    paneHeight = 700
    await act(async () => {
      globalThis.fireResizeObservers()
    })
    await settle()
    expect(viewportTransform(container)).toBe('translate(0px,-444px) scale(1)')
  })

  it('scales the drawing to fit a 644-wide pane', async () => {
    const real = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'graph-pane') {
        return { width: 644, height: 1080, x: 0, y: 0, top: 0, left: 0, right: 644, bottom: 1080, toJSON() {} }
      }
      return real.call(this)
    })
    const { container } = render(<GraphView steps={stepsFrom(40000, 5)} />)
    await settle()
    expect(viewportTransform(container)).toContain('scale(0.69')
  })
})
