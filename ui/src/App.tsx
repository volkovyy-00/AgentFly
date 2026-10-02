import { GraphView } from './graph/GraphView'
import { useRecorder } from './graph/useRecorder'

function App() {
  const mock = new URLSearchParams(window.location.search).get('mock') === '1'
  const { steps, epoch, offline, newSession } = useRecorder(mock)

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-canvas text-base text-ink">
      <GraphView steps={steps} epoch={epoch} />
      {steps.length === 0 && (
        <p className="pointer-events-none absolute inset-0 grid place-items-center text-base text-muted">
          Waiting for agent actions…
        </p>
      )}
      {offline && (
        <div
          role="alert"
          className="absolute inset-x-0 top-0 z-20 bg-blocked px-4 py-2 pl-48 text-center text-base font-bold text-white"
        >
          OFFLINE - recorder not reachable
        </div>
      )}
      <button
        type="button"
        onClick={newSession}
        className="absolute left-4 top-2 z-30 rounded border-2 border-ink bg-white px-3 text-base leading-6 font-semibold text-ink"
      >
        New session
      </button>
    </main>
  )
}

export default App
