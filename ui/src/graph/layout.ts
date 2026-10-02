import { MarkerType, Position, type Edge, type EdgeMarker, type Node, type NodeHandle } from '@xyflow/react'
import type { Step } from './types'

// All sizes in px. Rows are 56 px apart; row i is the cell [56i, 56i + 56).
export const ROW_PITCH = 56
export const STEP_W = 400
export const STEP_H = 44
export const FILE_W = 220
export const HOST_W = 200
export const LANE_H = 24
export const GUTTER = 40
export const SIDE_PAD = 16
export const STEP_X = SIDE_PAD
export const FILE_X = STEP_X + STEP_W + GUTTER
export const HOST_X = FILE_X + FILE_W + GUTTER
export const CONTENT_W = HOST_X + HOST_W + SIDE_PAD
export const TOP_PAD = 48
export const BOTTOM_PAD = 24
// Hosts take the upper sub-slot of their anchor row, rules the lower one.
const HOST_DY = -26
const RULE_DY = 2
const FILE_DY = -12
// React Flow's default <Handle> is 6 px; the handles array mirrors that so the
// edge ends match before and after the browser measures the DOM.
const HANDLE = 6

// Literal hex for markers (SVG markers do not resolve CSS variables). Keep in
// sync with the --color-* theme values in ui/src/index.css.
export const EDGE_COLOR = {
  chain: '#6b7280',
  aux: '#9aa3b2',
  secret: '#d97706',
  blocked: '#dc2626',
  warned: '#7c3aed',
} as const

export type EdgeColorKey = keyof typeof EDGE_COLOR

/** Arrow at the target; userSpaceOnUse so strokeWidth 3 does not blow it up. */
function arrow(color: string): EdgeMarker {
  return {
    type: MarkerType.ArrowClosed,
    color,
    markerUnits: 'userSpaceOnUse',
    width: 8,
    height: 8,
  }
}

export type StepNode = Node<{ step: Step }, 'step'>
export type FileNode = Node<{ path: string; sensitive: boolean }, 'file'>
export type HostNode = Node<{ host: string }, 'host'>
export type RuleNode = Node<{ rule: string }, 'rule'>
export type GraphNode = StepNode | FileNode | HostNode | RuleNode

export interface Layout {
  nodes: GraphNode[]
  edges: Edge[]
  rowCount: number
}

function handle(
  id: string,
  type: 'source' | 'target',
  position: Position,
  w: number,
  h: number,
): NodeHandle {
  const half = HANDLE / 2
  const spot: Record<Position, [number, number]> = {
    [Position.Top]: [w / 2 - half, -half],
    [Position.Bottom]: [w / 2 - half, h - half],
    [Position.Left]: [-half, h / 2 - half],
    [Position.Right]: [w - half, h / 2 - half],
  }
  const [x, y] = spot[position]
  return { id, type, position, x, y, width: HANDLE, height: HANDLE }
}

const STEP_HANDLES: NodeHandle[] = [
  handle('t', 'target', Position.Top, STEP_W, STEP_H),
  handle('b', 'source', Position.Bottom, STEP_W, STEP_H),
  handle('r', 'source', Position.Right, STEP_W, STEP_H),
]

function boxHandles(w: number): NodeHandle[] {
  return [handle('l', 'target', Position.Left, w, LANE_H)]
}

const BASE = { draggable: false, selectable: false, focusable: false, style: { pointerEvents: 'all' as const } }

function rowCentre(row: number): number {
  return row * ROW_PITCH + ROW_PITCH / 2
}

function link(
  id: string,
  from: Step,
  to: string,
  style: Edge['style'],
  colorKey: EdgeColorKey,
  zIndex?: number,
): Edge {
  return {
    id,
    source: `step:${from.order}`,
    sourceHandle: 'r',
    target: to,
    targetHandle: 'l',
    style,
    markerEnd: arrow(EDGE_COLOR[colorKey]),
    zIndex,
  }
}

/**
 * Pure layout. Positions come only from a step's index in `steps`, never from
 * `step.order` (orders reach tens of thousands). A file, host or rule is one
 * box, level with the first step in the list that touches it.
 */
export function layoutGraph(steps: readonly Step[]): Layout {
  const fileRow = new Map<string, number>()
  const hostRow = new Map<string, number>()
  const ruleRow = new Map<string, number>()
  const secretFiles = new Set<string>()

  steps.forEach((step, row) => {
    if (step.file !== null) {
      if (!fileRow.has(step.file)) fileRow.set(step.file, row)
      if (step.sensitive) secretFiles.add(step.file)
    }
    if (step.host !== null && !hostRow.has(step.host)) hostRow.set(step.host, row)
    if (step.rule !== null && !ruleRow.has(step.rule)) ruleRow.set(step.rule, row)
  })

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, row) => {
    const cy = rowCentre(row)
    nodes.push({
      id: `step:${step.order}`,
      type: 'step',
      position: { x: STEP_X, y: cy - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { step },
      handles: STEP_HANDLES,
      ...BASE,
    })

    const previous = steps[row - 1]
    if (previous !== undefined) {
      edges.push({
        id: `chain:${previous.order}:${step.order}`,
        type: 'straight',
        source: `step:${previous.order}`,
        sourceHandle: 'b',
        target: `step:${step.order}`,
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
        markerEnd: arrow(EDGE_COLOR.chain),
      })
    }

    if (step.file !== null) {
      const secret = step.sensitive
      edges.push(
        link(
          `file-edge:${step.order}`,
          step,
          `file:${step.file}`,
          {
            stroke: secret ? 'var(--color-secret)' : 'var(--color-aux)',
            strokeWidth: 2,
          },
          secret ? 'secret' : 'aux',
        ),
      )
    }
    if (step.host !== null) {
      const blocked = step.verdict === 'blocked'
      edges.push(
        link(
          `host-edge:${step.order}`,
          step,
          `host:${step.host}`,
          blocked
            ? { stroke: 'var(--color-blocked)', strokeWidth: 2.5, strokeDasharray: '8 6' }
            : { stroke: 'var(--color-aux)', strokeWidth: 2 },
          blocked ? 'blocked' : 'aux',
          blocked ? 1 : undefined,
        ),
      )
    }
    if (step.rule !== null) {
      const warned = step.verdict === 'warned'
      edges.push(
        link(
          `rule-edge:${step.order}`,
          step,
          `rule:${step.rule}`,
          {
            stroke: warned ? 'var(--color-warned)' : 'var(--color-blocked)',
            strokeWidth: 2.5,
            strokeDasharray: '8 6',
          },
          warned ? 'warned' : 'blocked',
          1,
        ),
      )
    }
  })

  for (const [path, row] of fileRow) {
    nodes.push({
      id: `file:${path}`,
      type: 'file',
      position: { x: FILE_X, y: rowCentre(row) + FILE_DY },
      width: FILE_W,
      height: LANE_H,
      data: { path, sensitive: secretFiles.has(path) },
      handles: boxHandles(FILE_W),
      ...BASE,
    })
  }
  for (const [host, row] of hostRow) {
    nodes.push({
      id: `host:${host}`,
      type: 'host',
      position: { x: HOST_X, y: rowCentre(row) + HOST_DY },
      width: HOST_W,
      height: LANE_H,
      data: { host },
      handles: boxHandles(HOST_W),
      ...BASE,
    })
  }
  for (const [rule, row] of ruleRow) {
    nodes.push({
      id: `rule:${rule}`,
      type: 'rule',
      position: { x: HOST_X, y: rowCentre(row) + RULE_DY },
      width: HOST_W,
      height: LANE_H,
      data: { rule },
      handles: boxHandles(HOST_W),
      ...BASE,
    })
  }

  return { nodes, edges, rowCount: steps.length }
}
