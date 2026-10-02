import { BaseEdge, getBezierPath, getStraightPath, type Edge, type EdgeProps } from '@xyflow/react'
import { motion } from 'motion/react'
import { useState } from 'react'
import { useDimmed } from './dim'
import type { WipeData } from './layout'
import { useMs } from './motionPolicy'

const PAD = 12

export type WipeEdgeType = Edge<WipeData, 'wipe'>

/**
 * An edge that draws in once, on its first run, with an SVG mask: a rect in
 * user space that grows from the source along the dominant axis (all edges in
 * this layout run left to right or top to bottom). A mask works for solid and
 * dashed edges alike and also reveals the arrowhead. The mask is removed when
 * the wipe ends, so settled edges are plain paths. Whether it has played is
 * state, not an effect: StrictMode runs effects twice.
 */
export function WipeEdge(props: EdgeProps<WipeEdgeType>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data } = props
  const ms = useMs()
  const dimmed = useDimmed(id)
  const quiet = data?.quiet ?? true
  const [wiping, setWiping] = useState(() => !quiet && ms(1) > 0)

  const [path] =
    data?.shape === 'straight'
      ? getStraightPath({ sourceX, sourceY, targetX, targetY })
      : getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })

  const x = Math.min(sourceX, targetX) - PAD
  const y = Math.min(sourceY, targetY) - PAD
  const width = Math.abs(targetX - sourceX) + 2 * PAD
  const height = Math.abs(targetY - sourceY) + 2 * PAD
  const horizontal = Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
  const maskId = `wipe-${id}`
  const start = data?.start ?? 0
  const transition = {
    delay: ms(start) / 1000,
    duration: ms((data?.end ?? 0) - start) / 1000,
    ease: 'easeOut' as const,
  }

  return (
    <g className="dimmable" data-dim={dimmed}>
      {wiping && (
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" x={x} y={y} width={width} height={height}>
            {horizontal ? (
              <motion.rect
                x={x}
                y={y}
                height={height}
                fill="white"
                initial={{ width: 0 }}
                animate={{ width }}
                transition={transition}
                onAnimationComplete={() => setWiping(false)}
              />
            ) : (
              <motion.rect
                x={x}
                y={y}
                width={width}
                fill="white"
                initial={{ height: 0 }}
                animate={{ height }}
                transition={transition}
                onAnimationComplete={() => setWiping(false)}
              />
            )}
          </mask>
        </defs>
      )}
      <g mask={wiping ? `url(#${maskId})` : undefined}>
        <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      </g>
    </g>
  )
}
