export const IGNORE_KEY = 'agentfly_v2_ignore_session'

/** The session hidden by "New session", or null. Storage may be unavailable. */
export function readIgnored(): string | null {
  try {
    return window.sessionStorage.getItem(IGNORE_KEY)
  } catch {
    return null
  }
}

export function writeIgnored(session: string | null): void {
  try {
    if (session === null) window.sessionStorage.removeItem(IGNORE_KEY)
    else window.sessionStorage.setItem(IGNORE_KEY, session)
  } catch {
    // Storage blocked: "New session" then lasts until reload, which is fine.
  }
}
