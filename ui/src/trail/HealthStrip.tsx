import type { Health } from './useTrail'

interface HealthStripProps {
  offline: boolean
  health: Health
  session: string | null
}

const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/**
 * The header's recorder status. `last_hook_at` and `offline_guard_count` show only
 * when `/health` sent them; today it sends `{"ok": true}`, so they stay hidden.
 */
export function HealthStrip({ offline, health, session }: HealthStripProps) {
  if (offline) {
    return (
      <div className="tr-health off" role="status">
        <span className="tr-dot off" aria-hidden="true" />
        <strong>OFFLINE</strong>
      </div>
    )
  }
  const { lastHookAt, offlineGuardCount } = health
  return (
    <div className="tr-health" role="status" title={session === null ? 'Recorder up' : `Recorder up · session ${session}`}>
      <span className="tr-dot" aria-hidden="true" />
      <span className="hide-sm">Recorder up</span>
      {lastHookAt !== null && <span className="hide-md">· last hook {clock.format(lastHookAt)}</span>}
      {offlineGuardCount !== null && <span className="hide-md">· offline guard {offlineGuardCount}</span>}
    </div>
  )
}
