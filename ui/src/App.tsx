import { motion } from 'motion/react'
import { TIMING, dur } from './graph/choreography'
import { GraphView } from './graph/GraphView'
import { parseBurst } from './graph/mock'
import { useMs } from './graph/motionPolicy'
import { useRecorder } from './graph/useRecorder'

function App() {
  const params = new URLSearchParams(window.location.search)
  const mock = params.get('mock') === '1'
  const burst = mock ? parseBurst(params.get('burst')) : 1
  const { steps, epoch, secretSeen, offline, newSession } = useRecorder(mock, burst)
  const ms = useMs()

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-canvas text-base text-ink">
      <GraphView steps={steps} epoch={epoch} />
      {steps.length === 0 && (
        <p className="pointer-events-none absolute inset-0 grid place-items-center text-base text-muted">
          Waiting for agent actions…
        </p>
      )}
      {offline && (
        <motion.div
          role="alert"
          className="absolute inset-x-0 top-0 z-20 bg-blocked px-4 py-2 pl-80 text-center text-base font-bold text-white"
          initial={{ y: '-100%' }}
          animate={{ y: 0 }}
          transition={{ duration: ms(dur(TIMING.banner)) / 1000, ease: 'easeOut' }}
        >
          OFFLINE - recorder not reachable
        </motion.div>
      )}
      <button
        type="button"
        onClick={newSession}
        className="absolute left-4 top-2 z-30 rounded border-2 border-ink bg-white px-3 text-base leading-6 font-semibold text-ink"
      >
        New session
      </button>
      {secretSeen !== null && (
        <motion.span
          role="status"
          className="absolute left-48 top-2 z-30 rounded bg-secret px-3 text-base leading-6 font-bold text-ink"
          initial={secretSeen.quiet ? false : { opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{
            delay: ms(TIMING.chip.start) / 1000,
            duration: ms(dur(TIMING.chip)) / 1000,
          }}
        >
          SECRET SEEN
        </motion.span>
      )}
    </main>
  )
}

export default App
