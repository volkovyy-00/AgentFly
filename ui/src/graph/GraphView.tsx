import { PanOnScrollMode, ReactFlow, ReactFlowProvider, useReactFlow, type Viewport } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  INITIAL_GESTURE, clampViewport, decideMove, followTarget, gestureStep, hasAlarm, panExtent, rowsOf,
  slideOptions, type Gesture, type GestureEvent,
} from './camera'
import { DimContext, useBlockDim } from './dim'
import { layoutGraph } from './layout'
import { useMs } from './motionPolicy'
import { FileBox, HostBox, RuleBox, StepBox } from './nodes'
import { BUTTON_CLASSES } from './tones'
import type { PlacedStep } from './types'
import { usePaneSize } from './usePaneSize'
import { WipeEdge } from './WipeEdge'

// Module-level so React Flow does not see a new object on every render.
const nodeTypes = { step: StepBox, file: FileBox, host: HostBox, rule: RuleBox }
// Module level too: a new object each render would replay every wipe.
const edgeTypes = { wipe: WipeEdge }

interface Props {
  steps: readonly PlacedStep[]
  /** Bumps when the window resets. The drawing remounts, so the camera jumps and every box enters afresh. */
  epoch: number
}

/** The drawing. The camera is uncontrolled: only `setViewport` moves it. */
export function GraphView({ steps, epoch }: Props) {
  const ms = useMs()
  const dim = useBlockDim(steps, epoch, ms)
  return (
    <DimContext.Provider value={dim}>
      <ReactFlowProvider key={epoch}>
        <Drawing steps={steps} />
      </ReactFlowProvider>
    </DimContext.Provider>
  )
}

function Drawing({ steps }: { steps: readonly PlacedStep[] }) {
  const { ref, pane } = usePaneSize()
  const rf = useReactFlow()
  const ms = useMs()
  const layout = useMemo(() => layoutGraph(steps), [steps])
  const { first, last } = rowsOf(steps)
  const rows = useMemo(() => ({ first, last }), [first, last])
  const target = useMemo(() => followTarget(rows, pane), [rows, pane])
  const extent = useMemo(() => panExtent(rows, pane), [rows, pane])

  const gesture = useRef<Gesture>(INITIAL_GESTURE)
  const [following, setFollowing] = useState(true)
  const previous = useRef<{ lastRow: number } | null>(null)
  const previousPane = useRef(pane)

  const send = useCallback((event: GestureEvent): boolean => {
    const { next, reissue } = gestureStep(gesture.current, event)
    gesture.current = next
    setFollowing(next.following)
    return reissue
  }, [])

  const slideTo = (vp: Viewport): void => {
    void rf.setViewport(vp, slideOptions(ms))
  }
  const jumpTo = (vp: Viewport): void => {
    void rf.setViewport(vp)
  }

  // After each step change: jump, slide or leave the camera alone. Keyed on the
  // newest row only, so an unchanged poll (or a field update in place) never
  // moves the camera; `steps` and `target` are read fresh from this render.
  useEffect(() => {
    const was = previous.current
    const alarm = was !== null && hasAlarm(steps, was.lastRow)
    const decision = decideMove(was, { lastRow: last, alarm }, gesture.current.following)
    previous.current = { lastRow: last }
    if (decision.move === 'jump') {
      send({ type: 'resume' })
      jumpTo(target)
    } else if (decision.move === 'slide') {
      if (decision.following) send({ type: 'resume' })
      slideTo(target)
    }
  }, [last])

  // A pane resize while following jumps to the follow target. Keyed on the pane
  // only: a step change is handled (with a slide) by the effect above.
  useEffect(() => {
    if (previousPane.current === pane) return
    previousPane.current = pane
    if (gesture.current.following) jumpTo(target)
  }, [pane])

  // A paused viewer is clamped in place (instantly) when the extent or zoom
  // changes. `pane` and `rf` change only together with these or never.
  useEffect(() => {
    if (gesture.current.following) return
    const vp = rf.getViewport()
    const kept = { x: target.x, y: (vp.y * target.zoom) / vp.zoom, zoom: target.zoom }
    const clamped = clampViewport(kept, extent, pane)
    if (clamped.x !== vp.x || clamped.y !== vp.y || clamped.zoom !== vp.zoom) void rf.setViewport(clamped)
  }, [extent, target])

  return (
    <div ref={ref} data-testid="graph-pane" className="relative h-full w-full">
      <div className="fade-top h-full w-full">
        <ReactFlow
          nodes={layout.nodes}
          edges={layout.edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={target}
          translateExtent={extent}
          minZoom={target.zoom}
          maxZoom={target.zoom}
          onMoveStart={(event) => {
            if (event === null) return
            send({ type: 'start', user: true })
            // React Flow reports the first wheel event as a start and a move only
            // from the second, so a single notch would read as a click.
            if (event.type === 'wheel') send({ type: 'move', user: true })
          }}
          onMove={(event) => {
            if (event !== null) send({ type: 'move', user: true })
          }}
          onMoveEnd={(event) => {
            const again = send({ type: 'end', user: event !== null })
            if (!again) return
            const now = rf.getViewport()
            if (now.x !== target.x || now.y !== target.y || now.zoom !== target.zoom) slideTo(target)
          }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          panOnDrag
          panOnScroll
          panOnScrollMode={PanOnScrollMode.Vertical}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling
          deleteKeyCode={null}
        />
      </div>
      {!following && (
        <button
          type="button"
          onClick={() => {
            send({ type: 'resume' })
            slideTo(target)
          }}
          className={`absolute right-4 top-2 ${BUTTON_CLASSES}`}
        >
          Follow
        </button>
      )}
    </div>
  )
}
