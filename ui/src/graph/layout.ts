import { MarkerType, Position, type Edge, type EdgeMarker, type Node, type NodeHandle } from '@xyflow/react'
import { enterDelay } from './choreography'
import type { PlacedStep, Step } from './types'

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
export const TOP_PAD = 96
export const BOTTOM_PAD = 24
// Hosts take the upper sub-slot of their anchor row, rules the lower one.
const HOST_DY = -26
const RULE_DY = 2
const FILE_DY = -12
// React Flow's default <Handle> is 6 px; the handles array mirrors that so the
// edge ends match before and after the browser measures the DOM. Keep the
// DOM <Handle> style size in nodes.tsx on this same constant.
export const HANDLE = 6

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

export const stepId = (order: number): string => `step:${order}`
export const fileId = (path: string): string => `file:${path}`
export const hostId = (host: string): string => `host:${host}`
export const ruleId = (rule: string): string => `rule:${rule}`
export const chainEdgeId = (from: number, to: number): string => `chain:${from}:${to}`
export const fileEdgeId = (order: number): string => `file-edge:${order}`
export const hostEdgeId = (order: number): string => `host-edge:${order}`
export const ruleEdgeId = (order: number): string => `rule-edge:${order}`

/** How a box or edge enters: nothing for a first-paint step, else after the step's stagger delay. */
export interface Enter {
  quiet: boolean
  delay: number
}

export const enterOf = (step: PlacedStep): Enter => ({ quiet: step.quiet, delay: enterDelay(step) })

/** What a shared box knows about the drawn steps that touch it. */
// A `type`, not an `interface`: React Flow requires node data to be a
// Record<string, unknown>, and an interface has no implicit index signature (TS2344).
export type BoxMeta = {
  /** Drawn steps touching the box. */
  count: number
  /** Row of the newest drawn toucher; advances when the box is reused. */
  lastTouchRow: number
  /** Row of the first drawn toucher, where the box sits. */
  anchorRow: number
  /** Entry timing, taken from the step the box first appeared with. */
  enter: Enter
}

export type StepNode = Node<{ step: PlacedStep }, 'step'>
export type FileNode = Node<{ path: string; sensitive: boolean } & BoxMeta, 'file'>
export type HostNode = Node<{ host: string } & BoxMeta, 'host'>
export type RuleNode = Node<{ rule: string } & BoxMeta, 'rule'>
export type GraphNode = StepNode | FileNode | HostNode | RuleNode

export interface Layout {
  nodes: GraphNode[]
  edges: Edge[]
}

/** Ids of what stays bright while a blocked step dims everything else. */
export function hotIds(step: Step): Set<string> {
  const ids = new Set([stepId(step.order)])
  if (step.host !== null) {
    ids.add(hostId(step.host))
    ids.add(hostEdgeId(step.order))
  }
  if (step.rule !== null) {
    ids.add(ruleId(step.rule))
    ids.add(ruleEdgeId(step.order))
  }
  return ids
}

function touch(boxes: Map<string, BoxMeta>, key: string, step: PlacedStep): void {
  const box = boxes.get(key)
  if (box === undefined) {
    boxes.set(key, { count: 1, lastTouchRow: step.row, anchorRow: step.row, enter: enterOf(step) })
  } else {
    box.count += 1
    box.lastTouchRow = step.row
  }
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

const FILE_HANDLES = boxHandles(FILE_W)
const HOST_HANDLES = boxHandles(HOST_W)

const BASE = { draggable: false, selectable: false, focusable: false, style: { pointerEvents: 'all' as const } }

function rowCentre(row: number): number {
  return row * ROW_PITCH + ROW_PITCH / 2
}

function link(
  id: string,
  from: PlacedStep,
  to: string,
  style: Edge['style'],
  colorKey: EdgeColorKey,
  zIndex?: number,
): Edge {
  return {
    id,
    source: stepId(from.order),
    sourceHandle: 'r',
    target: to,
    targetHandle: 'l',
    style,
    markerEnd: arrow(EDGE_COLOR[colorKey]),
    zIndex,
  }
}

/**
 * Pure layout. Positions come only from a step's `row` (fixed when first seen),
 * never from its place in the list or from `step.order`. A file, host or rule is
 * one box, level with the first step in the list that touches it.
 */
export function layoutGraph(steps: readonly PlacedStep[]): Layout {
  const files = new Map<string, BoxMeta>()
  const hosts = new Map<string, BoxMeta>()
  const rules = new Map<string, BoxMeta>()
  const secretFiles = new Set<string>()

  for (const step of steps) {
    if (step.file !== null) {
      touch(files, step.file, step)
      if (step.sensitive) secretFiles.add(step.file)
    }
    if (step.host !== null) touch(hosts, step.host, step)
    if (step.rule !== null) touch(rules, step.rule, step)
  }

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, index) => {
    const cy = rowCentre(step.row)
    nodes.push({
      id: stepId(step.order),
      type: 'step',
      position: { x: STEP_X, y: cy - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { step },
      handles: STEP_HANDLES,
      ...BASE,
    })

    const previous = steps[index - 1]
    if (previous !== undefined) {
      edges.push({
        id: chainEdgeId(previous.order, step.order),
        type: 'straight',
        source: stepId(previous.order),
        sourceHandle: 'b',
        target: stepId(step.order),
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
        markerEnd: arrow(EDGE_COLOR.chain),
      })
    }

    if (step.file !== null) {
      const secret = step.sensitive
      edges.push(
        link(
          fileEdgeId(step.order),
          step,
          fileId(step.file),
          { stroke: secret ? 'var(--color-secret)' : 'var(--color-aux)', strokeWidth: 2 },
          secret ? 'secret' : 'aux',
        ),
      )
    }
    if (step.host !== null) {
      const blocked = step.verdict === 'blocked'
      const elevate = blocked || step.verdict === 'warned'
      edges.push(
        link(
          hostEdgeId(step.order),
          step,
          hostId(step.host),
          blocked
            ? { stroke: 'var(--color-blocked)', strokeWidth: 2.5, strokeDasharray: '8 6' }
            : { stroke: 'var(--color-aux)', strokeWidth: 2 },
          blocked ? 'blocked' : 'aux',
          elevate ? 1 : undefined,
        ),
      )
    }
    if (step.rule !== null) {
      const warned = step.verdict === 'warned'
      edges.push(
        link(
          ruleEdgeId(step.order),
          step,
          ruleId(step.rule),
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

  for (const [path, meta] of files) {
    nodes.push({
      id: fileId(path),
      type: 'file',
      position: { x: FILE_X, y: rowCentre(meta.anchorRow) + FILE_DY },
      width: FILE_W,
      height: LANE_H,
      data: { path, sensitive: secretFiles.has(path), ...meta },
      handles: FILE_HANDLES,
      ...BASE,
    })
  }
  for (const [host, meta] of hosts) {
    nodes.push({
      id: hostId(host),
      type: 'host',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + HOST_DY },
      width: HOST_W,
      height: LANE_H,
      data: { host, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }
  for (const [rule, meta] of rules) {
    nodes.push({
      id: ruleId(rule),
      type: 'rule',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + RULE_DY },
      width: HOST_W,
      height: LANE_H,
      data: { rule, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }

  return { nodes, edges }
}
