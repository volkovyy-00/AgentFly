import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FileNode, HostNode, RuleNode, StepNode } from './layout'

const HIDDEN_HANDLE = { opacity: 0 } as const

function stepDetail(command: string | null, tool: string | null, kind: string): string {
  if (kind === 'read' || kind === 'edit') return ''
  return command ?? tool ?? ''
}

export function StepBox({ data }: NodeProps<StepNode>) {
  const { step } = data
  const detail = stepDetail(step.command, step.tool, step.kind)
  const tone =
    step.verdict === 'blocked'
      ? 'bg-blocked border-rule-edge'
      : step.verdict === 'warned'
        ? 'bg-warned border-warned'
        : 'bg-step border-step'
  const chip = step.verdict === 'blocked' ? 'BLOCKED' : step.verdict === 'warned' ? 'WARN' : null
  const chipTone = step.verdict === 'blocked' ? 'text-blocked' : 'text-warned'
  return (
    <div
      className={`flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 text-base leading-6 text-white ${tone}`}
      title={`${step.order}: ${step.kind}${detail ? ` ${detail}` : ''}`}
    >
      <Handle id="t" type="target" position={Position.Top} style={HIDDEN_HANDLE} />
      <span className="shrink-0 font-semibold">{step.kind}</span>
      <span className="min-w-0 flex-1 truncate font-mono">{detail}</span>
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
      <span dir="rtl" className="min-w-0 flex-1 truncate text-left font-mono">
        <bdi>{data.path}</bdi>
      </span>
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
