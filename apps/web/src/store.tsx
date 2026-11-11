/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { BranchInfo, Trace, VersionNode } from './data'
import { BASE, url } from './lib/url'

export type RunStatus = 'running' | 'validating' | 'succeeded'

export interface Run {
  id: string
  /** Version id this run will create when it succeeds. */
  nodeId: string
  status: RunStatus
  startedAt: number
  endedAt?: number
  resultNodeId?: string
}

export interface State {
  traces: Trace[]
  arrivedIds: string[]
  queueIndex: number
  versions: VersionNode[]
  currentId: string
  /** Branch HEAD is on; null when serving a mid-branch commit (detached). */
  currentBranch: string | null
  batchSize: number
  autoOptimize: boolean
  run: Run | null
  branches: BranchInfo[]
  model: string
}

const emptyState: State = {
  traces: [],
  arrivedIds: [],
  queueIndex: 0,
  versions: [],
  currentId: '',
  currentBranch: null,
  batchSize: 8,
  autoOptimize: false,
  run: null,
  branches: [],
  model: '',
}

/* ------------------------------------------------------------------- api */

let writeToken: string | null = null

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.method && init.method !== 'GET' && writeToken) {
    headers.set('authorization', `Bearer ${writeToken}`)
  }
  const res = await fetch(url(path), { ...init, headers })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    let message = `${res.status} ${body.slice(0, 200)}`
    try {
      const detail = JSON.parse(body)?.detail
      if (typeof detail === 'string') message = detail
    } catch {
      /* keep the raw body */
    }
    throw new Error(message)
  }
  return (res.headers.get('content-type')?.includes('json') ? res.json() : res.text()) as T
}

/* ----------------------------------------------------------------- store */

const StoreCtx = createContext<{ state: State; refresh: () => void } | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>(emptyState)
  const [ready, setReady] = useState(false)
  const arrived = useRef<Set<string>>(new Set())

  const refresh = useCallback(() => {
    api<any>('/api/state')
      .then((s) => {
        setState({
          traces: s.traces,
          arrivedIds: s.traces.filter((t: Trace) => arrived.current.has(t.id)).map((t: Trace) => t.id),
          queueIndex: 0,
          versions: s.versions,
          currentId: s.currentId,
          currentBranch: s.currentBranch ?? null,
          batchSize: s.batchSize,
          autoOptimize: s.autoOptimize,
          run: s.run ? { ...s.run, nodeId: s.run.resultVersionId ?? '' } : null,
          branches: s.branches ?? [],
          model: s.model ?? '',
        })
        setReady(true)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    api<{ writeToken: string | null }>('/api/ui-config')
      .then((c) => {
        writeToken = c.writeToken
      })
      .catch(() => {})
      .finally(refresh)
  }, [refresh])

  // Live updates: trace arrivals, run state, current version — no reload.
  useEffect(() => {
    if (!ready) return
    const es = new EventSource(url('/api/events'))
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'hello') return
        if (msg.type === 'demo_reset') {
          // Everything was rewound, the open page may show a run that is gone.
          window.location.replace(BASE)
          return
        }
        if (msg.type === 'trace_arrived') {
          const t = msg.trace as Trace
          if (msg.arrived) arrived.current.add(t.id)
          setState((s) =>
            s.traces.some((x) => x.id === t.id)
              ? { ...s, traces: s.traces.map((x) => (x.id === t.id ? { ...x, ...t } : x)) }
              : { ...s, traces: [t, ...s.traces], arrivedIds: [...s.arrivedIds, t.id] },
          )
          return
        }
        if (msg.type === 'trace_feedback') {
          setState((s) => ({
            ...s,
            traces: s.traces.map((x) =>
              x.id === msg.sessionId ? { ...x, feedback: msg.feedback } : x,
            ),
          }))
          return
        }
        if (msg.type === 'run_started') {
          setState((s) => ({
            ...s,
            run: { id: msg.run.id, nodeId: '', status: 'running', startedAt: Date.now() },
          }))
          return
        }
        if (msg.type === 'run_status') {
          setState((s) =>
            s.run && s.run.id === msg.runId
              ? { ...s, run: { ...s.run, status: msg.status, nodeId: msg.resultVersionId ?? s.run.nodeId } }
              : s,
          )
          return
        }
        if (
          msg.type === 'run_completed' ||
          msg.type === 'current_changed' ||
          msg.type === 'config_changed' ||
          msg.type === 'git_changed' ||
          msg.type === 'branch_created' ||
          msg.type === 'branch_renamed' ||
          msg.type === 'branch_merged'
        ) {
          refresh()
        }
      } catch {
        /* ignore malformed frames */
      }
    }
    return () => es.close()
  }, [ready, refresh])

  return <StoreCtx.Provider value={{ state, refresh }}>{children}</StoreCtx.Provider>
}

export function useStore() {
  const ctx = useContext(StoreCtx)
  if (!ctx) throw new Error('useStore outside provider')
  return ctx
}

/* ---------------------------------------------------------------- actions */

export const actions = {
  setBatchSize: (value: number) =>
    api('/api/config', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ batchSize: value }),
    }),
  toggleAuto: (autoOptimize: boolean) =>
    api('/api/config', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ autoOptimize }),
    }),
  startRun: () =>
    api<{ id: string }>('/api/optimize', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    }),
  setCurrent: (id: string) => api(`/api/versions/${id}/current`, { method: 'POST' }),
  createBranch: (name: string, fromNode?: string) =>
    api<{ name: string; tip: string }>('/api/branches', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, fromNode }),
    }),
  renameBranch: (from: string, to: string) =>
    api<{ name: string }>('/api/branches/rename', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ from, to }),
    }),
  mergeBranch: (name: string) =>
    api<{ id: string; merged: string; into: string }>(`/api/branches/${encodeURIComponent(name)}/merge`, {
      method: 'POST',
    }),
}

/* ------------------------------------------------------------ formatters */

export function relTime(ts: number): string {
  const d = Date.now() - ts
  const m = Math.round(d / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function fmtDuration(ms: number): string {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

