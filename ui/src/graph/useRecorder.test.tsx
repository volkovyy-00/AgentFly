import { act, renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IGNORE_KEY } from './ignoredSession'
import { MOCK_SESSION } from './mock'
import { stepsFrom } from './testing'
import type { Step } from './types'
import { MOCK_INTERVAL_MS, POLL_GAP_MS, POLL_TIMEOUT_MS, useRecorder } from './useRecorder'
import { WINDOW_SIZE } from './window'

type Body = { session: string | null; steps: Step[] }

function respond(body: Body): Response {
  return { ok: true, json: async () => body } as Response
}

/** A fetch that never answers until aborted, like a hung server. */
function hang(_url: unknown, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useRecorder (real mode)', () => {
  it('polls /api/steps right away and draws what comes back', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 10) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(fetchMock).toHaveBeenCalledWith('/api/steps', expect.objectContaining({ cache: 'no-store' }))
    expect(result.current.steps).toHaveLength(10)
    expect(result.current.offline).toBe(false)
  })

  it('keeps earlier steps across polls and stays within 20, from orders near 40,000', async () => {
    const bodies = [stepsFrom(40000, 10), stepsFrom(40005, 10), stepsFrom(40015, 10), stepsFrom(40025, 10), stepsFrom(40035, 10)]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: bodies[Math.min(call++, bodies.length - 1)] })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps.map((s) => s.order)).toEqual(stepsFrom(40000, 10).map((s) => s.order))
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(15)
    await advance(POLL_GAP_MS * 3)
    expect(result.current.steps).toHaveLength(20)
    expect(result.current.steps.at(-1)?.order).toBe(40044)
    expect(result.current.steps[0].order).toBe(40025)
  })

  it('goes OFFLINE within 3 s of the server dying, keeps the drawing, and recovers', async () => {
    let mode: 'up' | 'hung' = 'up'
    vi.stubGlobal('fetch', vi.fn((url: unknown, init?: RequestInit) =>
      mode === 'up' ? Promise.resolve(respond({ session: 's', steps: stepsFrom(40000, 3) })) : hang(url, init),
    ))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)

    mode = 'hung'
    await advance(POLL_GAP_MS + POLL_TIMEOUT_MS - 100)
    expect(result.current.offline).toBe(false)
    await advance(200)
    expect(result.current.offline).toBe(true)
    expect(POLL_GAP_MS + POLL_TIMEOUT_MS).toBeLessThan(3000)
    expect(result.current.steps).toHaveLength(3)

    mode = 'up'
    await advance(POLL_GAP_MS + 10)
    expect(result.current.offline).toBe(false)
  })

  it('treats a refused connection, a bad status and a bad body as OFFLINE', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('refused'))
      .mockResolvedValueOnce({ ok: false, json: async () => ({}) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => 'nope' } as Response)
      .mockResolvedValue(respond({ session: null, steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))

    await advance(0)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(true)
    await advance(POLL_GAP_MS)
    expect(result.current.offline).toBe(false)
  })

  it('empties on {session: null, steps: []} (after a server restart)', async () => {
    const bodies: Body[] = [{ session: 's', steps: stepsFrom(40000, 3) }, { session: null, steps: [] }]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond(bodies[Math.min(call++, 1)])))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(0)
  })

  it('New session empties the graph, stores the id, and keeps it empty', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    act(() => result.current.newSession())
    expect(result.current.steps).toHaveLength(0)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBe('s')
    await advance(POLL_GAP_MS * 3)
    expect(result.current.steps).toHaveLength(0)
  })

  it('New session still empties the graph when sessionStorage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
    act(() => result.current.newSession())
    await advance(POLL_GAP_MS * 2)
    expect(result.current.steps).toHaveLength(0)
  })

  it('a response already in flight when New session is clicked does not refill the graph', async () => {
    let release: (r: Response) => void = () => {}
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: 's', steps: stepsFrom(40000, 3) }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 3) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    await advance(POLL_GAP_MS)
    act(() => result.current.newSession())
    await act(async () => {
      release(respond({ session: 's', steps: stepsFrom(40000, 4) }))
    })
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
  })

  it('stays empty across a reload until a different session id arrives', async () => {
    window.sessionStorage.setItem(IGNORE_KEY, 's')
    let session = 's'
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session, steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
    session = 't'
    await advance(POLL_GAP_MS)
    expect(result.current.steps).toHaveLength(3)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBeNull()
  })

  it('stops polling on unmount', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = renderHook(() => useRecorder(false))
    await advance(0)
    unmount()
    const calls = fetchMock.mock.calls.length
    await advance(POLL_GAP_MS * 5)
    expect(fetchMock.mock.calls.length).toBe(calls)
  })

  it('runs one polling loop under StrictMode', async () => {
    const fetchMock = vi.fn(async () => respond({ session: 's', steps: [] }))
    vi.stubGlobal('fetch', fetchMock)
    renderHook(() => useRecorder(false), { wrapper: StrictMode })
    await advance(100)
    const before = fetchMock.mock.calls.length
    await advance(3000)
    expect(fetchMock.mock.calls.length - before).toBe(3)
  })
  it('marks only the first successful response as quiet', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: 's', steps: stepsFrom(40000, 3) }))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 5) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true, true])
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true, true, false, false])
  })

  it('an empty first response still uses up "first", so later steps animate', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ session: null, steps: [] }))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 2) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.steps).toHaveLength(0)
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([false, false])
  })

  it('a failed first poll does not use up "first"', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('refused'))
      .mockResolvedValue(respond({ session: 's', steps: stepsFrom(40000, 2) }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    await advance(POLL_GAP_MS)
    expect(result.current.steps.map((s) => s.quiet)).toEqual([true, true])
  })

  it('bumps epoch when the server restarts and numbering goes backwards', async () => {
    const bodies: Body[] = [
      { session: 's', steps: stepsFrom(40000, 10) },
      { session: 's', steps: stepsFrom(0, 3) },
    ]
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async () => respond(bodies[Math.min(call++, 1)])))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    const epoch = result.current.epoch
    await advance(POLL_GAP_MS)
    expect(result.current.epoch).toBe(epoch + 1)
    expect(result.current.steps.map((s) => s.row)).toEqual([0, 1, 2])
  })

  it('exposes secretSeen once a sensitive step arrives', async () => {
    const secret = { ...stepsFrom(40000, 1)[0], kind: 'read' as const, file: '.env', sensitive: true, command: null }
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: [secret] })))
    const { result } = renderHook(() => useRecorder(false))
    expect(result.current.secretSeen).toBeNull()
    await advance(0)
    expect(result.current.secretSeen).toEqual({ quiet: true, delay: 0 })
  })
})

describe('useRecorder (mock mode)', () => {
  it('replays the scenario one step per 1.5 s without calling the server', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRecorder(true))
    expect(result.current.steps).toHaveLength(1)
    for (let n = 2; n <= MOCK_SESSION.length; n++) {
      await advance(MOCK_INTERVAL_MS)
      expect(result.current.steps).toHaveLength(Math.min(n, WINDOW_SIZE))
    }
    await advance(MOCK_INTERVAL_MS * 3)
    expect(result.current.steps).toHaveLength(WINDOW_SIZE)
    expect(result.current.steps[0].order).toBe(40014)
    expect(result.current.steps.at(-1)?.order).toBe(40033)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.offline).toBe(false)
  })

  it('emits `burst` steps per tick', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true, 10))
    expect(result.current.steps).toHaveLength(10)
    await advance(MOCK_INTERVAL_MS)
    expect(result.current.steps).toHaveLength(20)
  })

  it('ignores burst in real mode', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3) })))
    const { result } = renderHook(() => useRecorder(false, 10))
    await advance(0)
    expect(result.current.steps).toHaveLength(3)
  })

  it('New session restarts the scenario', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true))
    await advance(MOCK_INTERVAL_MS * 4)
    expect(result.current.steps).toHaveLength(5)
    act(() => result.current.newSession())
    expect(result.current.steps).toHaveLength(1)
    expect(window.sessionStorage.getItem(IGNORE_KEY)).toBeNull()
  })

  it('mock steps are never quiet by default', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true))
    await advance(0)
    expect(result.current.steps[0].quiet).toBe(false)
  })

  it('with mockFirst, only the first tick of a page load paints still, even after New session', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const { result } = renderHook(() => useRecorder(true, 10, true))
    expect(result.current.steps).toHaveLength(10)
    expect(result.current.steps.every((s) => s.quiet)).toBe(true)
    await advance(MOCK_INTERVAL_MS)
    expect(result.current.steps.slice(10).every((s) => !s.quiet)).toBe(true)
    act(() => result.current.newSession())
    expect(result.current.steps.every((s) => !s.quiet)).toBe(true)
  })
})
