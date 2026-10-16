import type { ReactNode } from 'react'
import type { Step } from '../graph/types'
import { RETAINED_STEPS, RULE_COMMANDS, between, triggerFor, what, type Trigger } from './model'

const SEVERITY: Record<string, string> = { blocked: 'block', warned: 'warn', highlighted: 'highlight' }
const TONE: Record<string, string> = { blocked: 'blk', warned: 'wrn', highlighted: 'hl' }
const CHIP: Record<string, string> = { blocked: 'Blocked', warned: 'Warned', highlighted: 'Highlight' }
const OUTCOME: Record<string, string> = {
  blocked: 'the action did not run',
  warned: 'the action was allowed',
  highlighted: 'the action was allowed, with a mark',
}

const NOT_RECORDED = 'Contents not recorded'

function Mono({ children }: { children: ReactNode }) {
  return <span className="tr-mono">{children}</span>
}

function verbOf(step: Step): string {
  if (step.verdict === 'blocked') return 'tried'
  return step.kind === 'read' ? 'read' : 'ran'
}

function Title({ alarm, trigger }: { alarm: Step; trigger: Trigger }) {
  const rule = alarm.rule ?? 'rule not recorded'
  return (
    <>
      {trigger.kind === 'step' && (
        <>
          <span className="tr-nowrap">Step&nbsp;{trigger.step.order}</span> {trigger.step.kind === 'read' ? 'read' : 'ran'}{' '}
          <Mono>{what(trigger.step)}</Mono> →{' '}
        </>
      )}
      <span className="tr-nowrap">Step&nbsp;{alarm.order}</span> {verbOf(alarm)} <Mono>{what(alarm)}</Mono> → {rule}
      {alarm.verdict === 'warned' && ' warning'}
      {alarm.verdict === 'highlighted' && ' highlight'}
    </>
  )
}

function StepBox({ step, tone, small }: { step: Step; tone: 'sec' | 'blk' | 'wrn' | 'hl'; small: string }) {
  const chip = tone === 'sec' ? 'Secret read' : CHIP[step.verdict]
  return (
    <div className={`tr-box ${tone}`}>
      <span className="tr-stepn">STEP {step.order}</span>
      <span className={`tr-chip ${tone === 'sec' ? 'secret' : TONE[step.verdict]}`}>{chip}</span>
      <div className="t">
        <span className="tr-kind">{step.kind}</span>
        <Mono>{what(step)}</Mono>
      </div>
      <small>{small}</small>
    </div>
  )
}

/** Two dashed lines when there is a host and a rule, one when there is only one of them. */
function Ends({ alarm }: { alarm: Step }) {
  const both = alarm.host !== null && alarm.rule !== null
  if (alarm.host === null && alarm.rule === null) return null
  return (
    <>
      <svg className="tr-dash" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
        {both ? (
          <>
            <line x1="25" y1="0" x2="25" y2="34" />
            <line x1="75" y1="0" x2="75" y2="34" />
          </>
        ) : (
          <line x1="50" y1="0" x2="50" y2="34" />
        )}
      </svg>
      <div className="tr-ends" data-both={both}>
        {alarm.host !== null && <div className="tr-host">{alarm.host}</div>}
        {alarm.rule !== null && <div className="tr-pill">{alarm.rule}</div>}
      </div>
    </>
  )
}

function Messages({ alarm }: { alarm: Step }) {
  const items: [string, string][] = []
  if (alarm.rule_text) items.push(['Rule text', alarm.rule_text])
  if (alarm.user_message) items.push(['To you (user_message)', alarm.user_message])
  if (alarm.agent_message) items.push(['To the agent (agent_message)', alarm.agent_message])
  if (items.length === 0) {
    return <p className="tr-note">The recorder did not send the rule text or the messages for this step.</p>
  }
  return (
    <>
      <h3>Messages sent</h3>
      {items.map(([label, body]) => (
        <div className="tr-msg" key={label}>
          <b>{label}</b>
          {body}
        </div>
      ))}
    </>
  )
}

function TriggerNote({ trigger }: { trigger: Trigger }) {
  if (trigger.kind === 'unknown') {
    return <p className="tr-note">The step that marked this session is not known: the recorder did not report it.</p>
  }
  if (trigger.kind === 'evicted') {
    return (
      <p className="tr-note">
        The step that marked this session (Step&nbsp;{trigger.order}) is older than the last {RETAINED_STEPS} steps.
      </p>
    )
  }
  return null
}

interface WhyCardProps {
  alarm: Step | null
  steps: readonly Step[]
  markedOrder: number | null
  /** The step the owner picked has dropped out of the last 500: the newest block shows instead. */
  pickedGone: boolean
  onHide: () => void
}

export function WhyCard({ alarm, steps, markedOrder, pickedGone, onHide }: WhyCardProps) {
  const hide = (
    <button type="button" className="tr-btn" onClick={onHide} aria-label="Hide the Why card (w)" title="Hide (w)">
      Hide
    </button>
  )
  if (alarm === null) {
    return (
      <div className="tr-why-body">
        <div className="tr-why-head">
          <h2>No blocks or warnings yet</h2>
          {hide}
        </div>
        <p className="tr-note">When the recorder blocks or warns about a step, the reason shows here.</p>
      </div>
    )
  }
  const trigger = triggerFor(alarm, steps, markedOrder)
  const tone = TONE[alarm.verdict] as 'blk' | 'wrn' | 'hl'
  const mid = trigger.kind === 'step' ? between(steps, trigger.step.order, alarm.order) : null
  return (
    <div className="tr-why-body">
      <div className="tr-why-head">
        <h2>
          <Title alarm={alarm} trigger={trigger} />
        </h2>
        {hide}
      </div>
      {pickedGone && (
        <p className="tr-note">The step you picked is older than the last {RETAINED_STEPS} steps, so the newest block is shown.</p>
      )}
      <p className="tr-rule-line">
        Rule <b>{alarm.rule ?? 'not recorded'}</b> · severity {SEVERITY[alarm.verdict]} · {OUTCOME[alarm.verdict]}
        {alarm.verdict === 'blocked' && ', decided in memory before the action ran'}
      </p>
      <TriggerNote trigger={trigger} />
      <div className={`tr-chain${trigger.kind === 'step' ? '' : ' solo'}`}>
        {trigger.kind === 'step' && (
          <>
            <StepBox step={trigger.step} tone="sec" small={`marks the session · ${NOT_RECORDED}`} />
            <div className="tr-vlink amber" />
            {mid !== null && mid.routine + mid.flagged > 0 ? (
              <div className="tr-box mid">
                {mid.routine} routine step{mid.routine === 1 ? '' : 's'}
                {mid.flagged > 0 && ` and ${mid.flagged} flagged`} between
              </div>
            ) : (
              <div className="tr-box mid">next step</div>
            )}
            <div className="tr-vlink" />
          </>
        )}
        <StepBox step={alarm} tone={tone} small={NOT_RECORDED} />
        <Ends alarm={alarm} />
      </div>
      <Messages alarm={alarm} />
      <h3>To change this rule</h3>
      <pre className="tr-cmd">{RULE_COMMANDS.join('\n')}</pre>
      <p className="tr-note">This page is read-only: it shows the commands, it cannot change a rule or allow a step.</p>
    </div>
  )
}
