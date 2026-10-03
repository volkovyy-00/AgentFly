import { MarkerType, Position, type Edge, type EdgeMarker, type Node, type NodeHandle } from '@xyflow/react'
import { TIMING, enterDelay, type Span } from './choreography'
import type { Group, Hidden, PlacedStep, Step } from './types'

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
  blocked: '#ef4444',
  warned: '#a78bfa',
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
export const SUMMARY_ID = 'summary'
export const groupEdgeId = (order: number): string => `group-edge:${order}`
export const MAX_LANE_BOXES = 15
export const MAX_RULE_BOXES = 5

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

export type StepNode = Node<{ step: PlacedStep; flagged: boolean; marked: boolean }, 'step'>
export type SummaryNode = Node<{ hidden: Hidden }, 'summary'>
export type FileNode = Node<{ path: string; sensitive: boolean } & BoxMeta, 'file'>
export type HostNode = Node<{ host: string } & BoxMeta, 'host'>
export type RuleNode = Node<{ rule: string } & BoxMeta, 'rule'>
export type GraphNode = StepNode | SummaryNode | FileNode | HostNode | RuleNode

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
const SUMMARY_HANDLES: NodeHandle[] = [handle('b', 'source', Position.Bottom, STEP_W, STEP_H)]

function boxHandles(w: number): NodeHandle[] {
  return [handle('l', 'target', Position.Left, w, LANE_H)]
}

const FILE_HANDLES = boxHandles(FILE_W)
const HOST_HANDLES = boxHandles(HOST_W)

const BASE = { draggable: false, selectable: false, focusable: false, style: { pointerEvents: 'all' as const } }

function rowCentre(row: number): number {
  return row * ROW_PITCH + ROW_PITCH / 2
}

/** Per-edge data for the first-run draw-in. `start` and `end` are ms from the poll's arrival. */
export interface WipeData extends Record<string, unknown> {
  shape: 'straight' | 'bezier'
  quiet: boolean
  start: number
  end: number
}

function wipe(step: PlacedStep, shape: WipeData['shape'], span: Span): WipeData {
  const delay = enterDelay(step)
  return { shape, quiet: step.quiet, start: delay + span.start, end: delay + span.end }
}

function link(
  id: string,
  from: PlacedStep,
  to: string,
  style: Edge['style'],
  colorKey: EdgeColorKey,
  zIndex: number | undefined,
  span: Span,
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
    type: 'wipe',
    data: wipe(from, 'bezier', span),
  }
}

/** The flagged steps that are drawn: ascending, each order once, none already in the window. */
export function drawnFlagged(steps: readonly PlacedStep[], group: Group | null): Step[] {
  if (group === null || steps.length === 0) return []
  const seen = new Set(steps.map((s) => s.order))
  return group.flagged
    .filter((s) => {
      if (seen.has(s.order)) return false
      seen.add(s.order)
      return true
    })
    .sort((a, b) => a.order - b.order)
}

/** Rows the group takes above the oldest window row: the summary plus the drawn flagged steps. */
export function groupRows(steps: readonly PlacedStep[], group: Group | null): number {
  return group === null || steps.length === 0 ? 0 : 1 + drawnFlagged(steps, group).length
}

interface Candidate {
  id: string
  meta: BoxMeta
  /** A file is dropped before a host on a tie. */
  rank: number
}

/**
 * Ids over the cap, least recently touched first. Ties break by a fixed key that
 * never changes as the window slides (kind, then id), so a box cannot come back
 * without a touch. `anchorRow` is not a tie-break: it changes when a toucher leaves.
 */
function overCap(candidates: Candidate[], max: number): string[] {
  if (candidates.length <= max) return []
  const byId = (a: Candidate, b: Candidate): number => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  return candidates
    .sort((a, b) => a.meta.lastTouchRow - b.meta.lastTouchRow || a.rank - b.rank || byId(a, b))
    .slice(0, candidates.length - max)
    .map((c) => c.id)
}

const QUIET_WIPE: WipeData = { shape: 'straight', quiet: true, start: 0, end: 0 }

/** A step box at the step's own row; window steps and flagged steps differ only in `flagged`. */
function stepNode(step: PlacedStep, flagged: boolean, markedOrder: number | null): StepNode {
  return {
    id: stepId(step.order),
    type: 'step',
    position: { x: STEP_X, y: rowCentre(step.row) - STEP_H / 2 },
    width: STEP_W,
    height: STEP_H,
    data: { step, flagged, marked: step.order === markedOrder },
    handles: STEP_HANDLES,
    ...BASE,
  }
}

/** A straight chain edge from one box's bottom to the next box's top. */
function chainEdge(id: string, source: string, target: string, data: WipeData): Edge {
  return {
    id,
    type: 'wipe',
    data,
    source,
    sourceHandle: 'b',
    target,
    targetHandle: 't',
    style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
    markerEnd: arrow(EDGE_COLOR.chain),
  }
}

/**
 * Pure layout. Positions come only from a step's `row` (fixed when first seen),
 * never from its place in the list or from `step.order`. A file, host or rule is
 * one box, level with the first step in the list that touches it; at most 15
 * file/host boxes and 5 rule boxes are drawn. The group (summary box, then the
 * flagged steps) sits in the rows directly above the oldest window row; its
 * boxes and edges are always quiet, and only window steps touch shared boxes.
 */
export function layoutGraph(
  steps: readonly PlacedStep[],
  group: Group | null = null,
  markedOrder: number | null = null,
): Layout {
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

  const dropped = new Set([
    ...overCap(
      [
        ...[...files].map(([path, meta]) => ({ id: fileId(path), meta, rank: 0 })),
        ...[...hosts].map(([host, meta]) => ({ id: hostId(host), meta, rank: 1 })),
      ],
      MAX_LANE_BOXES,
    ),
    ...overCap(
      [...rules].map(([rule, meta]) => ({ id: ruleId(rule), meta, rank: 0 })),
      MAX_RULE_BOXES,
    ),
  ])

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, index) => {
    nodes.push(stepNode(step, false, markedOrder))

    const previous = steps[index - 1]
    if (previous !== undefined) {
      edges.push(
        chainEdge(
          chainEdgeId(previous.order, step.order),
          stepId(previous.order),
          stepId(step.order),
          wipe(step, 'straight', TIMING.chain),
        ),
      )
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
          undefined,
          TIMING.edge,
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
          blocked ? TIMING.blockEdge : TIMING.edge,
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
          TIMING.blockEdge,
        ),
      )
    }
  })

  if (group !== null && steps.length > 0) {
    const flagged = drawnFlagged(steps, group)
    const summaryRow = steps[0].row - 1 - flagged.length
    nodes.push({
      id: SUMMARY_ID,
      type: 'summary',
      position: { x: STEP_X, y: rowCentre(summaryRow) - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { hidden: group.hidden },
      handles: SUMMARY_HANDLES,
      ...BASE,
    })
    let upstream = SUMMARY_ID
    flagged.forEach((step, i) => {
      const placed: PlacedStep = { ...step, row: summaryRow + 1 + i, quiet: true, slot: 0, of: 1 }
      nodes.push(stepNode(placed, true, markedOrder))
      edges.push(chainEdge(groupEdgeId(step.order), upstream, stepId(step.order), QUIET_WIPE))
      upstream = stepId(step.order)
    })
  }

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

  // A box over the cap goes, and every edge into it goes with it.
  return { nodes: nodes.filter((n) => !dropped.has(n.id)), edges: edges.filter((e) => !dropped.has(e.target)) }
}
