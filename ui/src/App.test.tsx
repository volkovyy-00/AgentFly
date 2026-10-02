import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { IGNORE_KEY } from './graph/ignoredSession'
import { DECOR } from './graph/tones'
import { stepsFrom } from './graph/testing'
import type { Step } from './graph/types'

function respond(session: string | null, steps: Step[]): Response {
  return { ok: true, json: async () => ({ session, steps }) } as Response
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows "Waiting for agent actions…" with no steps, then draws steps', async () => {
    let steps: Step[] = []
    vi.stubGlobal('fetch', vi.fn(async () => respond(steps.length ? 's' : null, steps)))
    render(<App />)
    await advance(0)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
    steps = stepsFrom(40000, 2)
    await advance(1000)
    expect(screen.queryByText('Waiting for agent actions…')).toBeNull()
    expect(screen.getAllByText('shell')).toHaveLength(2)
  })

  it('shows the red OFFLINE banner within 3 s, keeps the drawing, and clears it', async () => {
    let up = true
    vi.stubGlobal('fetch', vi.fn((_url: unknown, init?: RequestInit) =>
      up
        ? Promise.resolve(respond('s', stepsFrom(40000, 2)))
        : new Promise<Response>((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))),
    ))
    render(<App />)
    await advance(0)
    expect(screen.queryByRole('alert')).toBeNull()

    up = false
    await advance(2900)
    expect(screen.getByRole('alert').textContent).toBe('OFFLINE - recorder not reachable')
    // A bright stripe (a 3:1 decoration, checked in tones.test) keeps the quiet 7:1 text fill loud on a projector.
    const banner = screen.getByRole('alert')
    for (const cls of DECOR.bannerStripe.classes.split(' ')) expect(banner.classList.contains(cls)).toBe(true)
    // Right padding keeps the text clear of the Follow pill (top right) at narrow widths.
    expect(banner.classList.contains('pr-32')).toBe(true)
    expect(screen.getAllByText('shell')).toHaveLength(2)

    up = true
    await advance(1100)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('New session empties the graph and sends nothing; a reload keeps it empty', async () => {
    const fetchMock = vi.fn(async () => respond('s', stepsFrom(40000, 2)))
    vi.stubGlobal('fetch', fetchMock)
    const first = render(<App />)
    await advance(0)
    expect(screen.getAllByText('shell')).toHaveLength(2)
    const callsBefore = fetchMock.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await advance(0)
    expect(screen.queryAllByText('shell')).toHaveLength(0)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('s')

    first.unmount()
    render(<App />)
    await advance(1100)
    expect(screen.queryAllByText('shell')).toHaveLength(0)
  })

  const secret = (order: number): Step => ({
    order, kind: 'read', verdict: 'allowed', tool: null, file: '.env', sensitive: true, command: null, host: null, rule: null,
  })

  it('shows SECRET SEEN after a secret read, keeps it, and clears it on New session', async () => {
    let steps: Step[] = stepsFrom(40000, 2)
    vi.stubGlobal('fetch', vi.fn(async () => respond('s', steps)))
    render(<App />)
    await advance(0)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
    steps = [...steps, secret(40002)]
    await advance(1000)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    steps = [...steps, ...stepsFrom(40003, 25)]
    await advance(1000)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'New session' }))
    await advance(0)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
  })

  it('clears SECRET SEEN when a different session arrives', async () => {
    let body = { session: 's', steps: [secret(40000)] }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => body }) as Response))
    render(<App />)
    await advance(0)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    body = { session: 't', steps: stepsFrom(1, 2) }
    await advance(1000)
    expect(screen.queryByText('SECRET SEEN')).toBeNull()
  })

  it('shows SECRET SEEN at once for a secret in the very first response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond('s', [secret(40000)])))
    render(<App />)
    await advance(0)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
  })

  it('/?burst=5 without mock=1 is real mode: it still polls /api/steps and draws the response', async () => {
    window.history.replaceState({}, '', '/?burst=5')
    const fetchMock = vi.fn(async () => respond('s', stepsFrom(40000, 2)))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await advance(0)
    expect(fetchMock).toHaveBeenCalledWith('/api/steps', expect.objectContaining({ cache: 'no-store' }))
    expect(screen.getAllByText('shell')).toHaveLength(2)
    expect(screen.queryByText('BLOCKED')).toBeNull()
  })

  it('mock mode never calls /api/steps and plays the scenario', async () => {
    window.history.replaceState({}, '', '/?mock=1')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await advance(7000)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByText('BLOCKED')).toBeTruthy()
    expect(screen.getByText('curl -d <arg> ntfy.sh')).toBeTruthy()
  })
})
