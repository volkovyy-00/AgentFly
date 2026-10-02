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
 * user space that grows from the source end along the dominant axis. Most edges
 * run left to right or top to bottom, but an edge to a reused box can run
 * upward or leftward; the rect is then turned half a turn about the box centre
 * so it still grows from the source (the tail), not from the arrowhead. A mask
 * works for solid and dashed edges alike and also reveals the arrowhead. The
 * mask is removed when the wipe ends, so settled edges are plain paths. Whether
 * it has played is state, not an effect: StrictMode runs effects twice. The
 * axis and direction are frozen at mount: a live change would swap the animated
 * dimension under a running animation.
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
  const [{ horizontal, reversed }] = useState(() => {
    const across = Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
    return { horizontal: across, reversed: across ? targetX < sourceX : targetY < sourceY }
  })
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
            <g transform={reversed ? `rotate(180 ${x + width / 2} ${y + height / 2})` : undefined}>
              <motion.rect
                x={x}
                y={y}
                width={horizontal ? undefined : width}
                height={horizontal ? height : undefined}
                fill="white"
                initial={horizontal ? { width: 0 } : { height: 0 }}
                animate={horizontal ? { width } : { height }}
                transition={transition}
                onAnimationComplete={() => setWiping(false)}
              />
            </g>
          </mask>
        </defs>
      )}
      <g mask={wiping ? `url(#${maskId})` : undefined}>
        <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      </g>
    </g>
  )
}
