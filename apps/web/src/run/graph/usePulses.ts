import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunEvent } from '../events'
import type { RunModel } from '../model'

/**
 * One-shot motion the stream asks for, exactly when its event lands: a judge
 * asking a seat (pulse judge → seat), the seat answering (seat → judge), a
 * seat handing in its work, and a seat that fails or times out (a shake).
 * Replayed backlog never animates; only events that arrive while watching do.
 */

export type PulseTone = 'accent' | 'green'

export interface Pulse {
  id: number
  edge: string
  reverse: boolean
  tone: PulseTone
}

export interface Shake {
  seat: string
  tone: 'red' | 'amber'
  n: number
}

function cues(m: RunModel, ev: RunEvent): { pulse?: Omit<Pulse, 'id'>; shake?: Omit<Shake, 'n'> } {
  if (ev.kind !== 'agent_start' && ev.kind !== 'agent_end') return {}
  const seat = m.seats.find((s) => s.key === ev.agent)
  if (!seat) return {}
  const spans = m.lanes[ev.agent]?.spans ?? []
  if (ev.kind === 'agent_start') {
    const span = spans.find((s) => s.start === ev.at)
    return span?.followUp && !seat.judge ? { pulse: { edge: `out:${seat.key}`, reverse: true, tone: 'accent' } } : {}
  }
  const span = spans.find((s) => s.end === ev.at)
  if (seat.judge) return ev.ok ? { pulse: { edge: `judge:${seat.stage}`, reverse: false, tone: 'green' } } : { shake: { seat: seat.key, tone: 'red' } }
  if (!ev.ok) return { shake: { seat: seat.key, tone: span?.followUp ? 'amber' : 'red' } }
  return { pulse: { edge: `out:${seat.key}`, reverse: false, tone: span?.followUp ? 'accent' : 'green' } }
}

export function usePulses(model: RunModel, enabled: boolean) {
  const seen = useRef(model.events.length)
  const nextId = useRef(0)
  const [pulses, setPulses] = useState<Pulse[]>([])
  const [shakes, setShakes] = useState<Record<string, Shake>>({})

  useEffect(() => {
    const events = model.events
    // A restarted stream starts over; whatever was already folded is history.
    const from = events.length < seen.current ? events.length : seen.current
    seen.current = events.length
    if (!enabled) return
    const fresh: Pulse[] = []
    const shaken: Shake[] = []
    for (const ev of events.slice(from)) {
      const { pulse, shake } = cues(model, ev)
      if (pulse) fresh.push({ ...pulse, id: nextId.current++ })
      if (shake) shaken.push({ ...shake, n: nextId.current++ })
    }
    if (fresh.length) setPulses((p) => [...p, ...fresh].slice(-24))
    if (shaken.length) setShakes((s) => ({ ...s, ...Object.fromEntries(shaken.map((x) => [x.seat, x])) }))
  }, [model, enabled])

  const done = useCallback((id: number) => setPulses((p) => p.filter((x) => x.id !== id)), [])
  return { pulses, shakes, done }
}
