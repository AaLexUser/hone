/** When t3code shows this dashboard in a frame, its booth guide follows along through these messages. */
import { url } from './url'

export type FrameEvent =
  | { type: 'route'; path: string }
  | { type: 'start-pressed' }
  | { type: 'run-started'; runId: string; quick: boolean }
  | { type: 'run-finished'; runId: string; status: string }
  | { type: 'activity' }

/** The page that frames this one. Messages go to that origin only, and come only from it. */
const parentOrigin: string | null = (() => {
  if (window.parent === window) return null
  const ancestor = window.location.ancestorOrigins?.[0]
  if (ancestor) return ancestor
  try {
    return document.referrer ? new URL(document.referrer).origin : null
  } catch {
    return null
  }
})()

export function tellParent(event: FrameEvent) {
  if (parentOrigin === null) return
  window.parent.postMessage({ source: 'hone', ...event }, parentOrigin)
}

/** A run replays an approved recording in about a minute and a half, a real one takes about ten. */
export function tellRunStarted(runId: string) {
  if (parentOrigin === null) return
  fetch(url(`/api/runs/${runId}`))
    .then((res) => (res.ok ? res.json() : null))
    .then((run) => tellParent({ type: 'run-started', runId, quick: Boolean(run?.replayOf) }))
    .catch(() => tellParent({ type: 'run-started', runId, quick: false }))
}

if (parentOrigin !== null) {
  // The guide outlines the element it asks the visitor to use, marked with data-guide.
  window.addEventListener('message', (event) => {
    if (event.origin !== parentOrigin || event.source !== window.parent) return
    const data = event.data as { source?: unknown; highlight?: unknown } | null
    if (data?.source !== 'hone-guide') return
    const root = document.documentElement
    if (typeof data.highlight === 'string') root.dataset.guideHighlight = data.highlight
    else delete root.dataset.guideHighlight
  })
  // Touches inside the frame never reach the parent, which counts idle time.
  let last = 0
  const ping = () => {
    const now = Date.now()
    if (now - last < 2000) return
    last = now
    tellParent({ type: 'activity' })
  }
  for (const name of ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const) {
    window.addEventListener(name, ping, { capture: true, passive: true })
  }
}
