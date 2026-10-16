import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { usePaneSize } from '../graph/usePaneSize'
import type { Step } from '../graph/types'
import { ViewTabs } from '../ViewTabs'
import './trail.css'
import {
  HIDE_BAR_PX,
  cardBounds,
  layoutOf,
  readPrefs,
  resolveCardSize,
  writePrefs,
  type CardPrefs,
} from './cardPrefs'
import { HealthStrip } from './HealthStrip'
import {
  ALARM_UI,
  alarmsOf,
  groupSteps,
  isAlarm,
  kindCounts,
  newestAlarm,
  rangeLabel,
  triggerFor,
  what,
  type AlarmKind,
  type AlarmStep,
  type TrailItem,
} from './model'
import { Splitter } from './Splitter'
import { useTrail } from './useTrail'
import { WhyCard } from './WhyCard'

interface TrailViewProps {
  mock: boolean
  len: number
  burst: number
  rich: boolean
}

const ALARM_KINDS: readonly AlarmKind[] = ['blocked', 'warned', 'highlighted']

/** Pixels from the bottom of the list that still count as "at the newest step". */
const BOTTOM_SLACK_PX = 48
/** Where a picked row lands, from the top of the list. */
const PICK_OFFSET_PX = 160

function chipOf(step: Step): { cls: string; text: string } | null {
  if (isAlarm(step)) {
    const { tone, chip } = ALARM_UI[step.verdict]
    return { cls: tone, text: step.rule === null ? chip : `${chip} · ${step.rule}` }
  }
  return step.sensitive ? { cls: 'secret', text: 'Secret read' } : null
}

function What({ step }: { step: Step }) {
  return (
    <span className="tr-what">
      <span className="tr-kind">{step.kind}</span>
      <span className="tr-mono">{what(step)}</span>
      {step.host !== null && <span className="tr-note"> → {step.host}</span>}
    </span>
  )
}

interface StepRowProps {
  step: Step
  selected: boolean
  trigger: boolean
  onPick: (order: number) => void
}

/** A row that is never folded: a block, a warning, a highlight or a secret read. */
const StepRow = memo(function StepRow({ step, selected, trigger, onPick }: StepRowProps) {
  const chip = chipOf(step)
  const alarm = isAlarm(step)
  const cls = `tr-row ${alarm ? `alarm ${ALARM_UI[step.verdict].row}` : 'secret'}${trigger ? ' trigger' : ''}`
  const interactive = alarm
    ? {
        role: 'button' as const,
        tabIndex: 0,
        'aria-pressed': selected,
        onClick: () => onPick(step.order),
        onKeyDown: (e: ReactKeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onPick(step.order)
          }
        },
      }
    : {}
  return (
    <div className={cls} data-order={step.order} data-verdict={step.verdict} title={`order ${step.order}`} {...interactive}>
      <span className="tr-no">{step.order}</span>
      <What step={step} />
      <span className="tr-badges">
        {chip !== null && <span className={`tr-chip ${chip.cls}`}>{chip.text}</span>}
        {!alarm && <span className="tr-allowed">allowed</span>}
      </span>
    </div>
  )
})

interface GroupProps {
  group: Extract<TrailItem, { type: 'group' }>
  triggerOrder: number | null
  onLayout: () => void
}

/** A run of routine allowed steps folded into one row; open state survives polls (keyed by the first order). */
const Group = memo(function Group({ group, triggerOrder, onLayout }: GroupProps) {
  const { steps } = group
  const holdsTrigger = triggerOrder !== null && steps.some((s) => s.order === triggerOrder)
  return (
    <details className={`tr-group${holdsTrigger ? ' has-trigger' : ''}`} data-first={group.key} onToggle={onLayout}>
      <summary>
        <span className="tr-no">{rangeLabel(steps)}</span>
        <span className="tr-what tr-gsum">
          <span className="tr-caret" aria-hidden="true" />
          <b>
            {steps.length} allowed step{steps.length === 1 ? '' : 's'}
          </b>{' '}
          · {kindCounts(steps)}
        </span>
      </summary>
      <div className="tr-inner">
        {steps.map((s) => (
          <div className={`tr-row${s.order === triggerOrder ? ' trigger' : ''}`} key={s.order} data-order={s.order} title={`order ${s.order}`}>
            <span className="tr-no">{s.order}</span>
            <What step={s} />
            <span className="tr-badges">
              <span className="tr-allowed">allowed</span>
            </span>
          </div>
        ))}
      </div>
    </details>
  )
})

/** The row element for a step, or its group's summary when the step sits in a closed group. */
function rowElement(root: HTMLElement, order: number): HTMLElement | null {
  const el = root.querySelector<HTMLElement>(`[data-order="${order}"]`)
  if (el === null) return null
  const details = el.closest('details')
  if (details !== null && !details.open) return details.querySelector<HTMLElement>('summary')
  return el
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

export function TrailView({ mock, len, burst, rich }: TrailViewProps) {
  const { steps, session, markedOrder, offline, loaded, health } = useTrail(mock, len, burst, rich)
  const items = useMemo(() => groupSteps(steps), [steps])

  // Selection: while Follow is on, the newest block; picking a row turns Follow off and keeps it.
  const [follow, setFollow] = useState(true)
  const [picked, setPicked] = useState<number | null>(null)
  const newest = useMemo(() => newestAlarm(steps), [steps])
  const pickedStep = follow || picked === null ? undefined : steps.find((s): s is AlarmStep => s.order === picked && isAlarm(s))
  const pickedGone = !follow && picked !== null && pickedStep === undefined
  const selected = pickedStep ?? newest

  // A new session (or a restarted recorder) numbers its steps from 1 again: a pick from the old one means nothing.
  useEffect(() => {
    setPicked(null)
    setFollow(true)
  }, [session])
  // Turning Follow off freezes the card on what it shows now; otherwise it would keep jumping to each new block.
  const selectedOrder = selected?.order ?? null
  const stopFollowing = useCallback(() => {
    setFollow(false)
    setPicked((p) => p ?? selectedOrder)
  }, [selectedOrder])

  const trigger = selected === null ? null : triggerFor(selected, steps, markedOrder)
  const triggerOrder = trigger !== null && trigger.kind === 'step' ? trigger.step.order : null

  // The Why card: shown or hidden, and its size, remembered between visits.
  const [prefs, setPrefs] = useState<CardPrefs>(() => readPrefs())
  const [dragSize, setDragSize] = useState<number | null>(null)
  const { ref: mainRef, pane } = usePaneSize()
  const layout = layoutOf(pane.width)
  const extent = layout === 'stacked' ? pane.height : pane.width
  const [minCard, maxCard] = cardBounds(layout, extent)
  const cardSize = dragSize ?? resolveCardSize(layout, extent, layout === 'stacked' ? prefs.stacked : prefs.side)

  const savePrefs = useCallback((next: CardPrefs) => {
    setPrefs(next)
    writePrefs(next)
  }, [])
  const toggleHidden = useCallback(() => {
    setPrefs((p) => {
      const next = { ...p, hidden: !p.hidden }
      writePrefs(next)
      return next
    })
  }, [])
  const commitSize = useCallback(
    (px: number | null) => {
      setDragSize(null)
      savePrefs({ ...prefs, [layout]: px })
    },
    [layout, prefs, savePrefs],
  )

  // Trail list: scrolling, Follow and the rail.
  const listRef = useRef<HTMLDivElement | null>(null)
  const [tick, setTick] = useState(0)
  const bump = useCallback(() => setTick((t) => t + 1), [])
  const [rail, setRail] = useState<{ top: number; height: number } | null>(null)

  const pick = useCallback((order: number, scroll = false) => {
    setPicked(order)
    setFollow(false)
    if (scroll) {
      const list = listRef.current
      const row = list === null ? null : rowElement(list, order)
      if (list !== null && row !== null) list.scrollTop = row.offsetTop - PICK_OFFSET_PX
    }
  }, [])

  // `tick` bumps when the list is resized (the card was dragged, the banner appeared): Follow stays at the newest step.
  useLayoutEffect(() => {
    const list = listRef.current
    if (follow && list !== null) list.scrollTop = list.scrollHeight
  }, [follow, steps, offline, tick])

  function onListScroll(): void {
    const list = listRef.current
    if (follow && list !== null && list.scrollHeight - list.scrollTop - list.clientHeight > BOTTOM_SLACK_PX) stopFollowing()
  }

  useEffect(() => {
    const list = listRef.current
    if (list === null) return
    const observer = new ResizeObserver(bump)
    observer.observe(list)
    return () => observer.disconnect()
  }, [bump])

  // The rail runs from the marking step (the secret read) to the selected block.
  const railFrom = triggerOrder
  const railTo = selected !== null && railFrom !== null ? selected.order : null
  useLayoutEffect(() => {
    const list = listRef.current
    if (list === null || railFrom === null || railTo === null) {
      setRail(null)
      return
    }
    const a = rowElement(list, railFrom)
    const b = rowElement(list, railTo)
    if (a === null || b === null) {
      setRail(null)
      return
    }
    // Edge to edge: from the bottom of the secret-read row to the top of the selected row, so the line never cuts across their outlines.
    const top = a.offsetTop + a.offsetHeight
    const bottom = b.offsetTop
    setRail((r) => (r !== null && r.top === top && r.height === Math.max(0, bottom - top) ? r : { top, height: Math.max(0, bottom - top) }))
  }, [railFrom, railTo, items, tick])

  // Prev / Next within one kind of alarm.
  const go = useCallback(
    (kind: AlarmKind, dir: 1 | -1) => {
      const list = alarmsOf(steps, kind)
      if (list.length === 0) return
      const at = list.findIndex((s) => s.order === selected?.order)
      const i = at < 0 ? (dir > 0 ? 0 : list.length - 1) : Math.min(list.length - 1, Math.max(0, at + dir))
      pick(list[i].order, true)
    },
    [steps, selected, pick],
  )

  const selectedKind: AlarmKind = selected === null ? 'blocked' : selected.verdict
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return
      if (e.key === 'w') toggleHidden()
      else if (e.key === 'n') go(selectedKind, 1)
      else if (e.key === 'p') go(selectedKind, -1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [go, selectedKind, toggleHidden])

  const secretSeen = markedOrder !== null || steps.some((s) => s.sensitive)
  const folded = items.filter((i) => i.type === 'group').length
  const hidden = prefs.hidden

  const tracks = hidden ? `minmax(0, 1fr) ${HIDE_BAR_PX}px` : `minmax(0, 1fr) auto ${cardSize}px`
  const mainStyle: CSSProperties = layout === 'stacked' ? { gridTemplateRows: tracks } : { gridTemplateColumns: tracks }

  const barLabel =
    selected === null ? 'Why card · no blocks or warnings yet' : `Why card · ${selected.rule ?? 'no rule'} · Step ${selected.order}`

  return (
    <div className="tr" data-layout={layout}>
      <header className="tr-header">
        <h1>AgentFly</h1>
        <ViewTabs view="trail" />
        <span className="tr-chip count hide-md">{steps.length} steps</span>
        {secretSeen && <span className="tr-chip secret">Secret seen</span>}
        <span className="tr-spacer" />
        <HealthStrip offline={offline} health={health} session={session} />
      </header>
      {offline && (
        <div className="tr-offline" role="alert">
          OFFLINE - recorder not reachable
        </div>
      )}
      <main className="tr-main" ref={mainRef} style={mainStyle} data-hidden={hidden}>
        <section className="tr-trail-col" aria-label="Trail">
          <div className="tr-pinned">
            {ALARM_KINDS.map((kind) => {
              const list = alarmsOf(steps, kind)
              if (list.length === 0 && kind === 'highlighted') return null
              const at = list.findIndex((s) => s.order === selected?.order)
              return (
                <div className="tr-pin-row" key={kind} data-kind={kind}>
                  <span className="tr-lbl">
                    <b>
                      {list.length} {kind}
                    </b>
                  </span>
                  <span className="tr-pos">{at >= 0 ? `${at + 1} of ${list.length}` : ''}</span>
                  <button type="button" className={`tr-btn ${kind}`} disabled={list.length === 0} onClick={() => go(kind, -1)}>
                    ‹ Prev
                  </button>
                  <button type="button" className={`tr-btn ${kind}`} disabled={list.length === 0} onClick={() => go(kind, 1)}>
                    Next ›
                  </button>
                </div>
              )
            })}
          </div>
          <div className="tr-toolbar">
            <span>{folded} routine groups folded</span>
            <span className="tr-spacer" />
            <span className="tr-hint hide-sm">
              <kbd>n</kbd> <kbd>p</kbd> next / previous · <kbd>w</kbd> Why card
            </span>
            <button
              type="button"
              className="tr-btn follow"
              aria-pressed={follow}
              onClick={() => {
                if (follow) stopFollowing()
                else {
                  setFollow(true)
                  setPicked(null)
                }
              }}
            >
              Follow latest
            </button>
          </div>
          <div className="tr-list" ref={listRef} onScroll={onListScroll}>
            {rail !== null && railFrom !== null && railTo !== null && (
              <div className="tr-rail" data-from={railFrom} data-to={railTo} style={{ top: rail.top, height: rail.height }} />
            )}
            {steps.length === 0 && (
              <p className="tr-empty">
                {loaded ? 'Waiting for agent actions…' : offline ? 'No steps yet: the recorder is not reachable.' : 'Connecting to the recorder…'}
              </p>
            )}
            {items.map((item) =>
              item.type === 'group' ? (
                <Group key={`g${item.key}`} group={item} triggerOrder={triggerOrder} onLayout={bump} />
              ) : (
                <StepRow
                  key={item.step.order}
                  step={item.step}
                  selected={selected?.order === item.step.order}
                  trigger={item.step.order === triggerOrder}
                  onPick={pick}
                />
              ),
            )}
          </div>
        </section>
        {hidden ? (
          <button type="button" className="tr-hidebar" onClick={toggleHidden} aria-label="Show the Why card (w)" title="Show (w)">
            <span className="tr-hidebar-label">{barLabel}</span>
            <span className="tr-btn">Show</span>
          </button>
        ) : (
          <>
            <Splitter
              layout={layout}
              size={cardSize}
              min={minCard}
              max={maxCard}
              onResize={setDragSize}
              onCommit={commitSize}
            />
            <aside className="tr-why" aria-label="Why card" aria-live="polite">
              <WhyCard alarm={selected} steps={steps} markedOrder={markedOrder} pickedGone={pickedGone} onHide={toggleHidden} />
            </aside>
          </>
        )}
      </main>
    </div>
  )
}

