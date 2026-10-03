import { Handle, Position, type NodeProps } from '@xyflow/react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { TIMING, dur, enterDelay, sec } from './choreography'
import { useDimmed } from './dim'
import { HANDLE, type BoxMeta, type FileNode, type HostNode, type RuleNode, type StepNode } from './layout'
import { useMs, useReducedMotion } from './motionPolicy'
import { DECOR, TONES } from './tones'
import type { Step, Verdict } from './types'
import { useBoxMotion } from './useBoxMotion'

const HIDDEN_HANDLE = { opacity: 0, width: HANDLE, height: HANDLE } as const

const VERDICT_UI: Record<Verdict, { tone: string; wipe: string; chip: string | null; chipTone: string }> = {
  allowed: { tone: TONES.step.classes, wipe: '', chip: null, chipTone: '' },
  blocked: { tone: TONES.stepBlocked.classes, wipe: DECOR.wipeBlocked.classes, chip: 'BLOCKED', chipTone: TONES.chipBlocked.classes },
  warned: { tone: TONES.stepWarned.classes, wipe: DECOR.wipeWarned.classes, chip: 'WARN', chipTone: TONES.chipWarned.classes },
}

function stepDetail(step: Step): string {
  if (step.kind === 'read' || step.kind === 'edit') return step.file ?? ''
  return step.command ?? step.tool ?? ''
}

/** RTL + bdi so a long path truncates on the left and keeps the basename visible. */
function TruncatedPath({ path }: { path: string }) {
  return (
    <span dir="rtl" className="min-w-0 flex-1 truncate text-left font-mono">
      <bdi>{path}</bdi>
    </span>
  )
}

export function StepBox({ id, data }: NodeProps<StepNode>) {
  const { step } = data
  const ms = useMs()
  const reduced = useReducedMotion()
  const dimmed = useDimmed(id)
  const delay = enterDelay(step)
  const detail = stepDetail(step)
  const pathKind = step.kind === 'read' || step.kind === 'edit'
  const { tone, wipe, chip, chipTone } = VERDICT_UI[step.verdict]
  const alarm = step.verdict !== 'allowed'
  // Under reduced motion the border is static and always visible: no wipe at all.
  const staticBorder = step.quiet || reduced
  return (
    <div
      className="dimmable relative h-full w-full"
      data-dim={dimmed}
      title={`${step.order}: ${step.kind}${detail ? ` ${detail}` : ''}`}
    >
      <Handle id="t" type="target" position={Position.Top} style={HIDDEN_HANDLE} />
      <motion.div
        className={`relative flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 text-base leading-6 ${tone}`}
        initial={step.quiet ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: sec(ms(delay)), duration: sec(ms(dur(TIMING.step))), ease: 'easeOut' }}
      >
        <span className="shrink-0 font-semibold">{step.kind}</span>
        {pathKind ? (
          <TruncatedPath path={detail} />
        ) : (
          <span className="min-w-0 flex-1 truncate font-mono">{detail}</span>
        )}
        {chip !== null && (
          <span className={`shrink-0 rounded px-2 font-bold leading-5 ${chipTone}`}>{chip}</span>
        )}
        {alarm && (
          <motion.div
            aria-hidden
            data-testid="border-wipe"
            className={`pointer-events-none absolute -inset-0.5 rounded-lg border-2 ${wipe}`}
            initial={staticBorder ? false : { clipPath: 'inset(0 100% 0 0)' }}
            animate={{ clipPath: 'inset(0 0% 0 0)' }}
            transition={{
              delay: sec(ms(delay + TIMING.borderWipe.start)),
              duration: sec(ms(dur(TIMING.borderWipe))),
              ease: 'easeOut',
            }}
          />
        )}
      </motion.div>
      <Handle id="b" type="source" position={Position.Bottom} style={HIDDEN_HANDLE} />
      <Handle id="r" type="source" position={Position.Right} style={HIDDEN_HANDLE} />
    </div>
  )
}

interface LaneFrameProps {
  id: string
  meta: BoxMeta
  title: string
  className: string
  /** Rule boxes spring in; file and host boxes fade in. */
  spring?: boolean
  /** A live secret read pulses one ring. */
  ring?: boolean
  children: ReactNode
}

/**
 * Shared frame for file, host and rule boxes. The Handle sits outside the keyed
 * motion element so a re-anchor never remounts it (a remounted handle would
 * drop its edges). Entry runs once per mount; a re-anchor fades in at once and
 * replays neither the brighten nor the tick (only those since the re-anchor).
 */
function LaneFrame({ id, meta, title, className, spring = false, ring = false, children }: LaneFrameProps) {
  const ms = useMs()
  const reduced = useReducedMotion()
  const dimmed = useDimmed(id)
  const { reanchor, bump, tick, anchoredAt } = useBoxMotion(meta)
  const { quiet, delay } = meta.enter
  const firstRun = reanchor === 0
  const span = spring ? TIMING.ruleSpring : TIMING.laneBox
  const hidden = spring ? { opacity: 0, scale: 0.6 } : { opacity: 0 }
  const initial = firstRun ? (quiet ? false : hidden) : { opacity: 0 }
  const start = firstRun ? delay + span.start : 0
  const transition =
    spring && firstRun && !reduced
      ? { type: 'spring' as const, duration: sec(dur(span)), bounce: 0.3, delay: sec(start) }
      : {
          duration: sec(ms(firstRun ? dur(span) : dur(TIMING.reanchor))),
          delay: sec(ms(start)),
          ease: 'easeOut' as const,
        }
  return (
    <div className="dimmable relative h-full w-full" data-dim={dimmed} title={title}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <motion.div
        key={`anchor-${reanchor}`}
        className={`relative flex h-full w-full items-center ${className}`}
        initial={initial}
        animate={{ opacity: 1, scale: 1 }}
        transition={transition}
      >
        {children}
        {meta.count >= 2 && (
          <motion.span
            key={`tick-${tick}`}
            className="shrink-0 font-bold tabular-nums"
            initial={tick === anchoredAt.tick ? false : { y: 8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: sec(ms(200)) }}
          >
            x{meta.count}
          </motion.span>
        )}
        {ring && firstRun && !quiet && (
          <motion.div
            aria-hidden
            data-testid="ring"
            className={`pointer-events-none absolute inset-0 rounded border-2 ${DECOR.ring.classes}`}
            initial={{ opacity: 0.9, scale: 1 }}
            animate={{ opacity: 0, scale: 1.25 }}
            transition={{
              delay: sec(ms(delay + TIMING.secretRing.start)),
              duration: sec(ms(dur(TIMING.secretRing))),
              ease: 'easeOut',
            }}
          />
        )}
        {bump > anchoredAt.bump && (
          <motion.div
            key={`bump-${bump}`}
            aria-hidden
            data-testid="bump"
            className={`pointer-events-none absolute inset-0 rounded ${DECOR.flash.classes}`}
            initial={{ opacity: 0.5 }}
            animate={{ opacity: 0 }}
            transition={{ duration: sec(ms(TIMING.brighten.end)) }}
          />
        )}
      </motion.div>
    </div>
  )
}

export function FileBox({ id, data }: NodeProps<FileNode>) {
  const tone = data.sensitive ? TONES.fileSecret.classes : TONES.file.classes
  return (
    <LaneFrame
      id={id}
      meta={data}
      title={data.path}
      ring={data.sensitive}
      className={`gap-2 rounded px-2 text-base leading-6 ${data.sensitive ? '' : 'border-2'} ${tone}`}
    >
      <TruncatedPath path={data.path} />
      {data.sensitive && <span className="shrink-0 font-bold">SECRET</span>}
    </LaneFrame>
  )
}

export function HostBox({ id, data }: NodeProps<HostNode>) {
  return (
    <LaneFrame id={id} meta={data} title={data.host} className={`gap-2 rounded border-2 px-2 text-base leading-6 ${TONES.host.classes}`}>
      <span className="min-w-0 flex-1 truncate font-mono">{data.host}</span>
    </LaneFrame>
  )
}

export function RuleBox({ id, data }: NodeProps<RuleNode>) {
  return (
    <LaneFrame
      id={id}
      meta={data}
      title={`Rule ${data.rule}`}
      spring
      className={`justify-center gap-2 rounded-full px-2 text-base font-bold leading-5 border-2 ${TONES.rule.classes}`}
    >
      <span className="truncate">{data.rule}</span>
    </LaneFrame>
  )
}
