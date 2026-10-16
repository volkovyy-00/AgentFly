import { motion } from 'motion/react'
import { TIMING, dur, sec } from './graph/choreography'
import { GraphView } from './graph/GraphView'
import { parseBurst, parseLen } from './graph/mock'
import { useMs } from './graph/motionPolicy'
import { BUTTON_CLASSES, DECOR, TONES } from './graph/tones'
import { useRecorder } from './graph/useRecorder'
import { TrailView } from './trail/TrailView'
import { ViewTabs, viewOf } from './ViewTabs'

function GraphApp() {
  const params = new URLSearchParams(window.location.search)
  const mock = params.get('mock') === '1'
  const burst = mock ? parseBurst(params.get('burst')) : 1
  const mockFirst = mock && params.get('first') === '1'
  const mockLen = mock ? parseLen(params.get('len')) : null
  const { steps, group, markedOrder, epoch, secretSeen, offline, newSession } = useRecorder(mock, burst, mockFirst, mockLen)
  const ms = useMs()

  return (
    <div className={`flex h-dvh w-full flex-col ${TONES.app.classes}`}>
      <header className={`flex items-center gap-3 px-4 py-2 ${TONES.header.classes}`}>
        <h1 className="m-0 text-base font-semibold">AgentFly</h1>
        <ViewTabs view="graph" />
      </header>
      <main className={`relative min-h-0 w-full flex-1 overflow-hidden text-base ${TONES.app.classes}`}>
        <GraphView steps={steps} epoch={epoch} group={group} markedOrder={markedOrder} />
        {steps.length === 0 && (
          <p className={`pointer-events-none absolute inset-0 grid place-items-center text-base ${TONES.empty.classes}`}>
            Waiting for agent actions…
          </p>
        )}
        {offline && (
          <motion.div
            role="alert"
            className={`absolute inset-x-0 top-0 z-20 border-b-8 py-4 pl-80 pr-32 text-center text-base font-bold ${DECOR.bannerStripe.classes} ${TONES.banner.classes}`}
            initial={{ y: '-100%' }}
            animate={{ y: 0 }}
            transition={{ duration: sec(ms(dur(TIMING.banner))), ease: 'easeOut' }}
          >
            OFFLINE - recorder not reachable
          </motion.div>
        )}
        <button
          type="button"
          onClick={newSession}
          className={`absolute left-4 top-2 ${BUTTON_CLASSES}`}
        >
          New session
        </button>
        {secretSeen !== null && (
          <motion.span
            role="status"
            className={`absolute left-48 top-2 z-30 rounded px-3 py-0.5 text-base leading-6 font-bold ${TONES.chipSecret.classes}`}
            initial={secretSeen.quiet ? false : { opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              delay: sec(ms(secretSeen.delay + TIMING.chip.start)),
              duration: sec(ms(dur(TIMING.chip))),
            }}
          >
            SECRET SEEN
          </motion.span>
        )}
      </main>
    </div>
  )
}

/** `?mock=1&len=N&burst=B`: N steps (1 to 2000, default 500), B per tick (default all at once); `rich=1` adds the optional fields. */
function TrailApp() {
  const params = new URLSearchParams(window.location.search)
  const mock = params.get('mock') === '1'
  const len = parseLen(params.get('len')) ?? 500
  const burstRaw = Number(params.get('burst'))
  const burst = Number.isInteger(burstRaw) && burstRaw >= 1 && burstRaw <= len ? burstRaw : len
  return <TrailView mock={mock} len={len} burst={burst} rich={params.get('rich') === '1'} />
}

/** The trail is home (`/`); the lane graph is the Graph tab (`/?view=graph`). */
function App() {
  return viewOf(window.location.search) === 'graph' ? <GraphApp /> : <TrailApp />
}

export default App
