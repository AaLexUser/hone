import { useCallback, useEffect, useState } from 'react'
import type { Review, ReviewItem, RunRecord } from '../data'
import { useStore } from '../store'
import { parseRunEvent } from './events'
import type { RunEvent } from './events'
import { initialModel, isTerminal, reduceRun } from './model'
import type { RunModel } from './model'

const CONFIDENCE: readonly ReviewItem['confidence'][] = ['high', 'medium', 'low']

function reviewItems(v: unknown): ReviewItem[] {
  if (!Array.isArray(v)) return []
  return v.flatMap((x) => {
    if (!x || typeof x !== 'object' || typeof x.statement !== 'string') return []
    return [
      {
        statement: x.statement,
        traceIds: Array.isArray(x.traceIds) ? x.traceIds.filter((t: unknown) => typeof t === 'string') : [],
        confidence: CONFIDENCE.find((c) => c === x.confidence) ?? 'medium',
      },
    ]
  })
}

const texts = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [])

function parseReview(j: unknown): Review | null {
  if (!j || typeof j !== 'object') return null
  const r = j as Record<string, unknown>
  return {
    summary: typeof r.summary === 'string' ? r.summary : '',
    findings: reviewItems(r.findings),
    hypotheses: reviewItems(r.hypotheses),
    unresolved: texts(r.unresolved),
  }
}

/**
 * The run page's data: the run record, the typed model folded from the event
 * stream, and the review judge's findings once they exist. Events are batched
 * per animation frame, so a 600-event replay lands in a handful of renders.
 */
export function useRun(id: string) {
  const { refresh } = useStore()
  const [record, setRecord] = useState<RunRecord | null | undefined>(undefined)
  const [model, setModel] = useState<RunModel>(initialModel)
  const [review, setReview] = useState<Review | null>(null)
  const [epoch, setEpoch] = useState(0)
  const [arrivedAt, setArrivedAt] = useState(0)
  const [caughtUp, setCaughtUp] = useState(false)

  const loadRecord = useCallback(
    () =>
      fetch(`/api/runs/${id}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((rec: RunRecord | null) => setRecord(rec))
        .catch(() => {}),
    [id],
  )

  useEffect(() => {
    setRecord(undefined)
    setModel(initialModel)
    setReview(null)
    setCaughtUp(false)
    loadRecord()
  }, [loadRecord])

  useEffect(() => {
    const es = new EventSource(`/api/runs/${id}/events`)
    let queue: RunEvent[] = []
    let frame = 0
    let started = false
    let restarted = false
    let settled = false
    let catchUp = 0
    const flush = () => {
      frame = 0
      const batch = queue
      queue = []
      setModel((m) => reduceRun(m, batch))
      setArrivedAt(Date.now())
      if (restarted) {
        restarted = false
        setReview(null)
        setEpoch((e) => e + 1)
        loadRecord()
      } else if (settled) {
        loadRecord().then(refresh)
      }
      settled = false
    }
    es.onmessage = (e) => {
      const ev = parseRunEvent(e.data)
      if (!ev) return
      if (ev.kind === 'log' && ev.icon === 'start') {
        if (started) restarted = true
        started = true
      }
      if ((ev.kind === 'status' && isTerminal(ev.status)) || ev.kind === 'commit') settled = true
      queue.push(ev)
      if (!frame) frame = requestAnimationFrame(flush)
      // The server replays the backlog in one burst; what arrives after it is happening now.
      if (!catchUp) catchUp = window.setTimeout(() => setCaughtUp(true), 500)
    }
    return () => {
      es.close()
      cancelAnimationFrame(frame)
      clearTimeout(catchUp)
    }
  }, [id, loadRecord, refresh])

  // review.json lands a moment after the `report` event, so a miss is retried.
  const wantReview = model.reportAt !== null || !!record?.hasReport
  useEffect(() => {
    if (!wantReview) return
    let cancelled = false
    let timer = 0
    const load = (tries: number) =>
      fetch(`/api/runs/${id}/review`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null)
        .then((j) => {
          if (cancelled) return
          const parsed = parseReview(j)
          if (parsed) setReview(parsed)
          else if (tries > 0) timer = window.setTimeout(() => load(tries - 1), 1500)
        })
    load(20)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [id, wantReview, epoch])

  return { record, model, review, arrivedAt, caughtUp }
}

/**
 * Run time in the stream's own clock: the last event's `at` plus the wall time
 * since it arrived. It ticks once a second only while `live`, and a replay at
 * any speed reads the same as the events it shows.
 */
export function useRunClock(lastAt: number, arrivedAt: number, live: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!live) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [live])
  if (!live || !arrivedAt) return lastAt
  return lastAt + Math.max(0, now - arrivedAt)
}
