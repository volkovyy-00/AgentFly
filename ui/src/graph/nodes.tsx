import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FileNode, HostNode, RuleNode, StepNode } from './layout'
import type { Step, Verdict } from './types'

const HIDDEN_HANDLE = { opacity: 0 } as const

const VERDICT_UI: Record<Verdict, { tone: string; chip: string | null; chipTone: string }> = {
  allowed: { tone: 'bg-step border-step', chip: null, chipTone: '' },
  blocked: { tone: 'bg-blocked border-rule-edge', chip: 'BLOCKED', chipTone: 'text-blocked' },
  warned: { tone: 'bg-warned border-warned', chip: 'WARN', chipTone: 'text-warned' },
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

export function StepBox({ data }: NodeProps<StepNode>) {
  const { step } = data
  const detail = stepDetail(step)
  const pathKind = step.kind === 'read' || step.kind === 'edit'
  const { tone, chip, chipTone } = VERDICT_UI[step.verdict]
  return (
    <div
      className={`flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 text-base leading-6 text-white ${tone}`}
      title={`${step.order}: ${step.kind}${detail ? ` ${detail}` : ''}`}
    >
      <Handle id="t" type="target" position={Position.Top} style={HIDDEN_HANDLE} />
      <span className="shrink-0 font-semibold">{step.kind}</span>
      {pathKind ? (
        <TruncatedPath path={detail} />
      ) : (
        <span className="min-w-0 flex-1 truncate font-mono">{detail}</span>
      )}
      {chip !== null && (
        <span className={`shrink-0 rounded bg-white px-2 font-bold leading-5 ${chipTone}`}>{chip}</span>
      )}
      <Handle id="b" type="source" position={Position.Bottom} style={HIDDEN_HANDLE} />
      <Handle id="r" type="source" position={Position.Right} style={HIDDEN_HANDLE} />
    </div>
  )
}

export function FileBox({ data }: NodeProps<FileNode>) {
  const tone = data.sensitive ? 'bg-secret text-ink' : 'bg-link text-white'
  return (
    <div className={`flex h-full w-full items-center gap-2 rounded px-2 text-base leading-6 ${tone}`} title={data.path}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <TruncatedPath path={data.path} />
      {data.sensitive && <span className="shrink-0 font-bold">SECRET</span>}
    </div>
  )
}

export function HostBox({ data }: NodeProps<HostNode>) {
  return (
    <div className="flex h-full w-full items-center rounded bg-link px-2 text-base leading-6 text-white" title={data.host}>
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <span className="min-w-0 flex-1 truncate font-mono">{data.host}</span>
    </div>
  )
}

export function RuleBox({ data }: NodeProps<RuleNode>) {
  return (
    <div
      className="flex h-full w-full items-center justify-center rounded-full border-2 border-rule-edge bg-rule px-2 text-base font-bold leading-5 text-white"
      title={`Rule ${data.rule}`}
    >
      <Handle id="l" type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <span className="truncate">{data.rule}</span>
    </div>
  )
}
