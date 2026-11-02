import type { ProposedChange, ReviewItem } from '../data'
import type { Stage } from './events'
import type { Attempt, Lane, RunModel, Seat, Span } from './model'
import { isTerminal } from './model'

/* ------------------------------------------------------------- roster */

export interface LaneGroup {
  stage: Stage
  judge: Seat | null
  panel: Seat[]
}

const STAGES: readonly Stage[] = ['review', 'propose']

/** The groups come from the roster: one judge and however many panel seats it lists. */
export function laneGroups(m: RunModel): LaneGroup[] {
  return STAGES.map((stage) => {
    const seats = m.seats.filter((s) => s.stage === stage)
    return {
      stage,
      judge: seats.find((s) => s.judge) ?? null,
      panel: seats.filter((s) => !s.judge).sort((a, b) => a.n - b.n),
    }
  })
}

export const groupSeats = (g: LaneGroup): Seat[] => (g.judge ? [...g.panel, g.judge] : g.panel)

const PANEL_NOUN: Record<Stage, [string, string]> = {
  review: ['reviewer', 'reviewers'],
  propose: ['proposer', 'proposers'],
}

export const panelNoun = (stage: Stage, n: number) => `${n} ${PANEL_NOUN[stage][n === 1 ? 0 : 1]}`
export const stageName = (stage: Stage) => (stage === 'review' ? 'Review' : 'Propose')

export const seatLabel = (s: Seat) =>
  s.judge ? `${stageName(s.stage)} judge` : `${PANEL_NOUN[s.stage][0].replace(/^./, (c) => c.toUpperCase())} ${s.n}`

/** R1, R2, J … the two-letter chip that stands for a seat everywhere on the page. */
export const monogram = (s: Seat) => (s.judge ? 'J' : `${s.stage === 'review' ? 'R' : 'P'}${s.n}`)

/** `opencode-go/deepseek-v4.1-flash@high` reads as `deepseek-v4.1-flash`; the full id is in the tooltip and drawer. */
export const shortModel = (model: string) => (model.split('/').pop() ?? model).split('@')[0]

/* ---------------------------------------------------------- seat state */

export type LaneStatus = 'idle' | 'running' | 'done' | 'error'

export function laneStatus(lane: Lane | undefined): LaneStatus {
  const spans = lane?.spans ?? []
  if (!spans.length) return 'idle'
  if (spans.some((s) => s.end === null)) return 'running'
  const last = spans[spans.length - 1]
  return last.error && !last.followUp ? 'error' : 'done'
}

/** Wall time an agent spent working, follow-ups included; running spans count up to `now`. */
export const busyMs = (lane: Lane | undefined, now: number) =>
  (lane?.spans ?? []).reduce((sum, s: Span) => sum + ((s.end ?? now) - s.start), 0)

export const currentAttempt = (m: RunModel): Attempt => m.attempts[m.attempts.length - 1]

/** A seat's state in the attempt on screen: a proposer that crashed in attempt 1 starts clean in attempt 2. */
export function seatStatus(m: RunModel, seat: Seat): LaneStatus {
  const lane = m.lanes[seat.key]
  if (seat.stage === 'review' || !lane) return laneStatus(lane)
  const n = currentAttempt(m).n
  const spans = lane.spans.filter((s) => s.attempt === n)
  if (!spans.length) {
    // A failed run keeps the last attempt that ran on screen.
    return isTerminal(m.outcome) ? laneStatus(lane) : 'idle'
  }
  return laneStatus({ ...lane, spans })
}

/* ------------------------------------------------------ cross-examining */

export interface Cross {
  /** Follow-ups this seat answered (panel seats) or asked for (judge). */
  answered: number
  timedOut: number
  /** A follow-up is open right now and involves this seat. */
  live: boolean
}

/** Per seat key: what the judge's ask_panel follow-ups did, for the attempt on screen. */
export function crossExam(m: RunModel, stage: Stage): Record<string, Cross> {
  const n = currentAttempt(m).n
  const asks = m.followUps.filter((f) => f.stage === stage && (stage === 'review' || f.attempt === n))
  const out: Record<string, Cross> = {}
  const add = (key: string, answered: number, timedOut: number, live: boolean) => {
    const c = (out[key] ??= { answered: 0, timedOut: 0, live: false })
    c.answered += answered
    c.timedOut += timedOut
    c.live ||= live
  }
  const judge = m.seats.find((s) => s.stage === stage && s.judge)
  for (const f of asks) {
    const open = f.end === null
    for (const key of f.answered) {
      const timedOut = f.timedOut.includes(key)
      const answering = m.lanes[key]?.spans.some((s) => s.followUp && s.end === null) ?? false
      add(key, timedOut ? 0 : 1, timedOut ? 1 : 0, open && answering)
    }
    if (judge) add(judge.key, f.answered.length - f.timedOut.length, f.timedOut.length, open)
  }
  return out
}

/* ------------------------------------------------------------- stages */

export type StageState = 'pending' | 'active' | 'done' | 'retry' | 'failed' | 'skipped'

export function stageState(m: RunModel, stage: Stage): StageState {
  const windows = m.windows.filter((w) => w.stage === stage)
  const last = windows[windows.length - 1]
  if (!last) return m.outcome === 'failed' ? 'skipped' : 'pending'
  if (last.end === null) return 'active'
  if (last.failed) return isTerminal(m.outcome) ? 'failed' : 'retry'
  return 'done'
}

export type VerifyState = 'pending' | 'active' | 'passed' | 'rejected' | 'skipped'

/**
 * The verifier's state for the attempt on screen. An attempt whose propose
 * stage crashed never reached the verifier, so it leaves Verify untouched.
 */
export function verifyState(m: RunModel): VerifyState {
  const last = currentAttempt(m)
  if (last.verdict?.kind === 'passed') return m.outcome === 'no-changes' ? 'skipped' : 'passed'
  if (last.verdict?.kind === 'rejected') return 'rejected'
  if (m.outcome === 'failed') return m.attempts.some((a) => a.verdict?.kind === 'rejected') ? 'rejected' : 'skipped'
  if (last.verdict?.kind === 'crashed') return 'pending'
  const proposeStart = m.windows.filter((w) => w.stage === 'propose' && w.attempt === last.n).at(-1)
  if (proposeStart?.end != null && m.commitAt !== null && m.commitAt >= proposeStart.start) return 'active'
  return 'pending'
}

/* -------------------------------------------------------------- attempts */

export type Cause = 'provider error' | 'timed out' | 'rejected by the verifier' | 'stage failed'

export interface AttemptStory {
  n: number
  state: 'open' | 'passed' | 'rejected' | 'crashed'
  seat: Seat | null
  cause: Cause | null
  /** The error as a person reads it, e.g. `503 upstream overloaded`; the full text stays in `detail`. */
  plain: string
  detail: string
}

/** `…did not complete cleanly (stopReason: error): 503 upstream overloaded` reads as `503 upstream overloaded`. */
export const plainError = (text: string) => (/(?:\(stopReason: \w+\)|Error):?\s*([^:]*)$/.exec(text)?.[1] ?? text).trim() || text

function causeOf(text: string): Cause {
  if (/\b5\d\d\b|overloaded|stopReason: error|transport/i.test(text)) return 'provider error'
  if (/timeout|timed out/i.test(text)) return 'timed out'
  return 'stage failed'
}

/** Each attempt with the seat that sank it and a plain cause; verifier verdicts only where the verifier ran. */
export function attemptStories(m: RunModel): AttemptStory[] {
  return m.attempts.map((a) => {
    const v = a.verdict
    if (!v) return { n: a.n, state: 'open', seat: null, cause: null, plain: '', detail: '' }
    if (v.kind === 'passed') return { n: a.n, state: 'passed', seat: null, cause: null, plain: '', detail: '' }
    if (v.kind === 'rejected') {
      return { n: a.n, state: 'rejected', seat: null, cause: 'rejected by the verifier', plain: v.reason, detail: v.reason }
    }
    const seat =
      m.seats.find((s) => !s.judge && m.lanes[s.key]?.spans.some((p) => p.attempt === a.n && !p.followUp && p.error)) ?? null
    const err = seat ? (m.lanes[seat.key].spans.find((p) => p.attempt === a.n && p.error)?.error ?? v.reason) : v.reason
    return { n: a.n, state: 'crashed', seat, cause: causeOf(err), plain: plainError(err), detail: err }
  })
}

/* --------------------------------------------------------- now line */

export interface NowLine {
  stage: Stage | 'verify' | 'setup'
  text: string
}

const joinSeats = (seats: Seat[]) => seats.map(monogram).join(' and ').replace(/ and (?=.* and )/g, ', ')

/** The one short "now" line while a run is live; the graph carries the rest. */
export function nowLine(m: RunModel, sessions: number): NowLine | null {
  if (isTerminal(m.outcome)) return null
  const groups = laneGroups(m)
  const active = groups.find((g) => stageState(m, g.stage) === 'active')
  if (!active) {
    const last = currentAttempt(m)
    if (verifyState(m) === 'active') return { stage: 'verify', text: 'Verifying the edits against AGENTS.md' }
    if (last.verdict && last.verdict.kind !== 'passed') return { stage: 'propose', text: `Attempt ${last.n} failed, retrying` }
    if (stageState(m, 'review') === 'done') return { stage: 'propose', text: 'Starting the proposers' }
    return { stage: 'setup', text: `Freezing ${sessions} sessions` }
  }
  const ask = m.followUps.find((f) => f.stage === active.stage && f.end === null)
  if (ask) {
    const asked = active.panel.filter((s) => ask.answered.includes(s.key))
    return { stage: active.stage, text: asked.length ? `Judge cross-examines ${joinSeats(asked)}` : 'Judge cross-examines the panel' }
  }
  if (active.judge && seatStatus(m, active.judge) === 'running') {
    return { stage: active.stage, text: active.stage === 'review' ? 'Judge writes the report' : 'Judge fuses the drafts' }
  }
  const working = active.panel.filter((s) => seatStatus(m, s) === 'running')
  if (!working.length) return { stage: active.stage, text: `${stageName(active.stage)} starting` }
  const doing = active.stage === 'review' ? `reading ${sessions} sessions` : 'drafting edits'
  const who =
    working.length === active.panel.length
      ? panelNoun(active.stage, working.length)
      : `${working.length} of ${panelNoun(active.stage, active.panel.length)}`
  return { stage: active.stage, text: `${who} ${doing}` }
}

/* --------------------------------------------------------------- time */

export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

/* ------------------------------------------------- edits ⇄ findings */

const WORD = /[a-z0-9_]{4,}/g
const words = (s: string) => new Set(s.toLowerCase().match(WORD) ?? [])

function jaccard<T>(a: Set<T>, b: Set<T>): number {
  if (!a.size || !b.size) return 0
  let shared = 0
  for (const x of a) if (b.has(x)) shared++
  return shared / (a.size + b.size - shared)
}

/**
 * Which finding each verified edit acts on. The pipeline does not record the
 * link, so it is inferred: shared evidence sessions plus shared wording
 * between the edit's rationale and text and the finding's statement.
 */
export function linkEdits(changes: ProposedChange[], findings: ReviewItem[]): number[] {
  return changes.map((c) => {
    const evidence = new Set(c.evidence)
    const text = words(`${c.rationale} ${c.after ?? ''} ${c.before ?? ''}`)
    let best = -1
    let bestScore = 0.05
    findings.forEach((f, i) => {
      const score = jaccard(evidence, new Set(f.traceIds)) + 2 * jaccard(text, words(f.statement))
      if (score > bestScore) {
        best = i
        bestScore = score
      }
    })
    return best
  })
}
