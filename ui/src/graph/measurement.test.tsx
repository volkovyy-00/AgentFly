import { act, render } from '@testing-library/react'
import { Handle, Position, ReactFlow, type Edge, type Node } from '@xyflow/react'
import { describe, expect, it } from 'vitest'

// Guards the test setup itself. In a browser, React Flow measures each node and
// replaces its `handles` data with the <Handle> elements it finds in the DOM, so
// a node that renders no <Handle> loses its edges. If src/test-setup.ts ever
// regresses to a stub that never measures, the second test below fails and the
// real edge tests would otherwise pass for the wrong reason.

function Box({ data }: { data: { withHandle: boolean } }) {
  return (
    <div>
      {data.withHandle && <Handle id="r" type="source" position={Position.Right} />}
      {data.withHandle && <Handle id="l" type="target" position={Position.Left} />}
    </div>
  )
}

async function edgeCount(withHandle: boolean): Promise<number> {
  const nodes: Node[] = [
    { id: 'a', type: 'box', position: { x: 0, y: 0 }, width: 100, height: 40, data: { withHandle },
      handles: [{ id: 'r', type: 'source', position: Position.Right, x: 97, y: 17, width: 6, height: 6 }] },
    { id: 'b', type: 'box', position: { x: 300, y: 0 }, width: 100, height: 40, data: { withHandle },
      handles: [{ id: 'l', type: 'target', position: Position.Left, x: -3, y: 17, width: 6, height: 6 }] },
  ]
  const edges: Edge[] = [{ id: 'e', source: 'a', target: 'b', sourceHandle: 'r', targetHandle: 'l' }]
  const { container } = render(
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={{ box: Box }} viewport={{ x: 0, y: 0, zoom: 1 }} onViewportChange={() => {}} />,
  )
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })
  return container.querySelectorAll('.react-flow__edge').length
}

describe('test setup mimics browser measurement', () => {
  it('draws an edge between nodes that render handles', async () => {
    expect(await edgeCount(true)).toBe(1)
  })

  it('loses the edge when a node renders no <Handle>, as a browser would', async () => {
    expect(await edgeCount(false)).toBe(0)
  })
})
