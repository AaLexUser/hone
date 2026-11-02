import type { RunOutcome } from '../data'
import type { DraftEdit, RosterEntry, RunEvent, Stage } from './events'

/**
 * The run as the page sees it: one reducer folds the event stream into this
 * model. Layout reads the roster from here, never a fixed count.
 */

export interface Seat {
  key: string
  stage: Stage
  judge: boolean
  /** 1-based seat number in its panel; 0 for the judge. */
  n: number
  model: string
}

/** One stretch of work by one agent. Follow-ups are short spans that answer a judge's ask_panel. */
export interface Span {
  start: number
  end: number | null
  attempt: number
  followUp: boolean
  error?: string
}

export interface Lane {
  key: string
  spans: Span[]
  tools: number[]
}

export interface FollowUp {
  stage: Stage
  attempt: number
  start: number
  end: number | null
  answered: string[]
  timedOut: string[]
}

/** A stage's open interval within one attempt; review runs once, propose once per attempt. */
export interface StageWindow {
  stage: Stage
  attempt: number
  start: number
  end: number | null
  failed: boolean
}

export type Verdict =
  | { kind: 'passed'; at: number }
  | { kind: 'rejected'; at: number; reason: string }
  | { kind: 'crashed'; at: number; reason: string }

export interface Attempt {
  n: number
  verdict: Verdict | null
}

export interface Draft {
  agent: string
  attempt: number
  at: number
  note?: string
  edits: DraftEdit[]
}

export interface RunModel {
  seats: Seat[]
  lanes: Record<string, Lane>
  windows: StageWindow[]
  followUps: FollowUp[]
  attempts: Attempt[]
  drafts: Draft[]
  reportAt: number | null
  commitAt: number | null
  /** Verified edits revealed so far (`change` events). */
  revealed: number
  outcome: RunOutcome
  lastAt: number
  events: RunEvent[]
}

export const initialModel: RunModel = {
  seats: [],
  lanes: {},
  windows: [],
  followUps: [],
  attempts: [{ n: 1, verdict: null }],
  drafts: [],
  reportAt: null,
  commitAt: null,
  revealed: 0,
  outcome: 'running',
  lastAt: 0,
  events: [],
}

export const isTerminal = (o: RunOutcome) => o === 'succeeded' || o === 'failed' || o === 'no-changes'

export const VERDICT_LOG = /^Attempt (\d+) (rejected|stage failed)/

function toSeat(a: RosterEntry): Seat {
  const judge = a.role === 'judge'
  const n = judge ? 0 : Number(a.key.split('-').pop()) || 0
  return { key: a.key, stage: a.stage, judge, n, model: a.model }
}

const emptyLane = (key: string): Lane => ({ key, spans: [], tools: [] })

function updateLane(m: RunModel, key: string, fn: (lane: Lane) => Lane): RunModel {
  return { ...m, lanes: { ...m.lanes, [key]: fn(m.lanes[key] ?? emptyLane(key)) } }
}

const currentAttempt = (m: RunModel) => m.attempts[m.attempts.length - 1].n

function closeSpans(lane: Lane, at: number, error?: string): Lane {
  return {
    ...lane,
    spans: lane.spans.map((s) => (s.end === null ? { ...s, end: at, error: s.error ?? error } : s)),
  }
}

function setVerdict(m: RunModel, n: number, verdict: Verdict): RunModel {
  return {
    ...m,
    attempts: m.attempts.map((a) => (a.n === n && !a.verdict ? { ...a, verdict } : a)),
  }
}

function openFollowUp(m: RunModel, stage: Stage): FollowUp | undefined {
  return m.followUps.find((f) => f.stage === stage && f.end === null)
}

function step(m: RunModel, ev: RunEvent): RunModel {
  switch (ev.kind) {
    case 'pipeline': {
      const known = new Set(m.seats.map((s) => s.key))
      const added = ev.agents.filter((a) => !known.has(a.key)).map(toSeat)
      const attempts = m.attempts.some((a) => a.n === ev.attempt)
        ? m.attempts
        : [...m.attempts, { n: ev.attempt, verdict: null }]
      return { ...m, seats: added.length ? [...m.seats, ...added] : m.seats, attempts }
    }
    case 'stage': {
      const attempt = currentAttempt(m)
      if (ev.status === 'start') {
        return { ...m, windows: [...m.windows, { stage: ev.stage, attempt, start: ev.at, end: null, failed: false }] }
      }
      return {
        ...m,
        windows: m.windows.map((w) => (w.stage === ev.stage && w.end === null ? { ...w, end: ev.at } : w)),
      }
    }
    case 'agent_start': {
      const seat = m.seats.find((s) => s.key === ev.agent)
      const ask = seat && !seat.judge ? openFollowUp(m, seat.stage) : undefined
      const next = updateLane(m, ev.agent, (lane) => ({
        ...lane,
        spans: [...lane.spans, { start: ev.at, end: null, attempt: currentAttempt(m), followUp: !!ask }],
      }))
      if (!ask) return next
      return {
        ...next,
        followUps: next.followUps.map((f) => (f === ask ? { ...f, answered: [...f.answered, ev.agent] } : f)),
      }
    }
    case 'agent_end':
      return updateLane(m, ev.agent, (lane) => closeSpans(lane, ev.at, ev.ok ? undefined : (ev.error ?? 'failed')))
    case 'tool': {
      const next = updateLane(m, ev.agent, (lane) => ({ ...lane, tools: [...lane.tools, ev.at] }))
      if (ev.name !== 'ask_panel') return next
      const stage = m.seats.find((s) => s.key === ev.agent)?.stage ?? 'review'
      const ask: FollowUp = { stage, attempt: currentAttempt(m), start: ev.at, end: null, answered: [], timedOut: [] }
      return { ...next, followUps: [...next.followUps, ask] }
    }
    case 'ask_panel': {
      const open = openFollowUp(m, ev.stage)
      if (open) {
        return {
          ...m,
          followUps: m.followUps.map((f) => (f === open ? { ...f, end: ev.at, timedOut: ev.timedOut } : f)),
        }
      }
      const start = ev.at - ev.durationMs
      const closed = m.followUps.findLast((f) => f.stage === ev.stage && f.end !== null && f.end >= start)
      if (closed) {
        return { ...m, followUps: m.followUps.map((f) => (f === closed ? { ...f, timedOut: ev.timedOut } : f)) }
      }
      const ask: FollowUp = { stage: ev.stage, attempt: currentAttempt(m), start, end: ev.at, answered: [], timedOut: ev.timedOut }
      return { ...m, followUps: [...m.followUps, ask] }
    }
    case 'proposal':
      return {
        ...m,
        drafts: [...m.drafts, { agent: ev.agent, attempt: currentAttempt(m), at: ev.at, note: ev.note, edits: ev.edits }],
      }
    case 'report':
      return { ...m, reportAt: ev.at }
    case 'commit':
      return { ...m, commitAt: ev.at }
    case 'change':
      return setVerdict({ ...m, revealed: Math.max(m.revealed, ev.index + 1) }, currentAttempt(m), { kind: 'passed', at: ev.at })
    case 'log': {
      const match = VERDICT_LOG.exec(ev.text)
      if (match) {
        const n = Number(match[1])
        const reason = ev.detail ?? ''
        const verdict: Verdict =
          match[2] === 'rejected' ? { kind: 'rejected', at: ev.at, reason } : { kind: 'crashed', at: ev.at, reason }
        const windows = m.windows.map((w) => (w.end === null ? { ...w, end: ev.at, failed: verdict.kind === 'crashed' } : w))
        return setVerdict({ ...m, windows }, n, verdict)
      }
      if (ev.text.startsWith('Returned 0 edits')) {
        return setVerdict(m, currentAttempt(m), { kind: 'passed', at: ev.at })
      }
      return m
    }
    case 'status': {
      if (!isTerminal(ev.status)) return { ...m, outcome: ev.status }
      const lanes = Object.fromEntries(Object.entries(m.lanes).map(([k, lane]) => [k, closeSpans(lane, ev.at)]))
      const windows = m.windows.map((w) => (w.end === null ? { ...w, end: ev.at } : w))
      const done = { ...m, lanes, windows, outcome: ev.status }
      return ev.status === 'failed' ? done : setVerdict(done, currentAttempt(m), { kind: 'passed', at: ev.at })
    }
    case 'message':
    case 'retry':
      return m
    case 'tool_result': {
      // A stream without the analytics line still ends the follow-up when the judge's tool call returns.
      if (ev.name !== 'ask_panel') return m
      const stage = m.seats.find((s) => s.key === ev.agent)?.stage ?? 'review'
      const open = openFollowUp(m, stage)
      if (!open) return m
      return { ...m, followUps: m.followUps.map((f) => (f === open ? { ...f, end: ev.at } : f)) }
    }
  }
}

/** Folds a batch of events. A run-start log on a non-empty model means the stream restarted from byte zero. */
export function reduceRun(model: RunModel, batch: RunEvent[]): RunModel {
  let m = model
  let base = model.events
  const added: RunEvent[] = []
  let lastAt = model.lastAt
  for (const ev of batch) {
    if (ev.kind === 'log' && ev.icon === 'start' && base.length + added.length > 0) {
      m = initialModel
      base = []
      added.length = 0
      lastAt = 0
    }
    m = step(m, ev)
    added.push(ev)
    lastAt = Math.max(lastAt, ev.at)
  }
  return { ...m, events: [...base, ...added], lastAt }
}
