import { ReactFlow } from '@xyflow/react'
import { useMemo } from 'react'
import { layoutGraph } from './layout'
import { FileBox, HostBox, RuleBox, StepBox } from './nodes'
import type { Step } from './types'
import { usePaneSize } from './usePaneSize'
import { MIN_ZOOM, computeViewport } from './viewport'

// Module-level so React Flow does not see a new object on every render.
const nodeTypes = { step: StepBox, file: FileBox, host: HostBox, rule: RuleBox }

function ignoreViewportChange(): void {}

/** The drawing: React Flow, fully controlled (no pan, zoom, drag or selection). */
export function GraphView({ steps }: { steps: readonly Step[] }) {
  const { ref, pane } = usePaneSize()
  const layout = useMemo(() => layoutGraph(steps), [steps])
  const viewport = useMemo(() => computeViewport(layout.rowCount, pane), [layout.rowCount, pane])

  return (
    <div ref={ref} data-testid="graph-pane" className="h-full w-full">
      <ReactFlow
        nodes={layout.nodes}
        edges={layout.edges}
        nodeTypes={nodeTypes}
        viewport={viewport}
        onViewportChange={ignoreViewportChange}
        minZoom={MIN_ZOOM}
        maxZoom={1}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        deleteKeyCode={null}
      />
    </div>
  )
}
