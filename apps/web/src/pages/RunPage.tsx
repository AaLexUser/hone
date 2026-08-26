import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import {
  ChevronRight,
  Play,
  FileText,
  ScanLine,
  Lightbulb,
  PenLine,
  ShieldCheck,
  ArrowRight,
  RotateCw,
  XCircle,
  CircleSlash,
  MessageSquare,
  Bot,
  Wrench,
  GitBranch,
  Gavel,
  ScrollText,
  Layers,
} from 'lucide-react'
import { useStore, relTime, fmtDuration } from '../store'
import type { AgentState, LogEvent, PipelineAgent, ProposedChange, RunRecord, RunEvent } from '../data'
import { diffLines } from '../lib/diff'
import type { DiffRow } from '../lib/diff'
import { Badge } from '../components/ui'
import { PipelineGraph, type StageStates } from './PipelineGraph'

const icons = {
  start: Play,
  read: FileText,
  scan: ScanLine,
  note: Lightbulb,
  draft: PenLine,
  check: ShieldCheck,
  retry: RotateCw,
  fail: XCircle,
}

// Kinds shown in the activity feed. Change events drive the live change
// cards instead; the graph-driving kinds (pipeline) are kept in the stream
// but not rendered as feed rows.
const ACTIVITY_KINDS = new Set([
  'log', 'feedback', 'agent', 'tool', 'tool_result', 'commit',
  'message', 'proposal', 'agent_start', 'agent_end', 'stage', 'report',
])

const levelStyles: Record<string, string> = {
  warn: 'border-amber/30 bg-amber/10 text-amber',
  error: 'border-red/30 bg-red/10 text-red',
}

const opStyles: Record<ProposedChange['op'], string> = {
  insert: 'text-green bg-green/10 border-green/25',
  update: 'text-amber bg-amber/10 border-amber/30',
  delete: 'text-red bg-red/10 border-red/30',
}

/** One run page: the live MAJICS pipeline while it works, read-only replay after. */
export function RunPage() {
  const { id = '' } = useParams()
  const { state, refresh } = useStore()
  const [record, setRecord] = useState<RunRecord | null | undefined>(undefined)
  const [stream, setStream] = useState<LogEvent[]>([])
  const [shownChanges, setShownChanges] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const seen = useRef<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    const load = () =>
      fetch(`/api/runs/${id}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((rec: RunRecord | null) => {
          if (cancelled || !rec) return
          setRecord(rec)
          if (!['running', 'validating'].includes(rec.status) && rec.events?.length) {
            setStream(rec.events)
            setShownChanges(rec.changes.length)
          }
        })
        .catch(() => {})
    load()
    const poll = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(poll)
    }
  }, [id])

  // Live events: the run's events.jsonl streamed from byte zero, then tailed.
  useEffect(() => {
    const es = new EventSource(`/api/runs/${id}/events`)
    es.onmessage = (e) => {
      try {
        const ev: RunEvent = JSON.parse(e.data)
        const key = `${ev.kind}:${ev.at}:${ev.kind === 'log' ? ev.text : ev.kind === 'change' ? ev.index : (ev as any).status ?? (ev as any).agent ?? ''}`
        if (seen.current.has(key)) return
        seen.current.add(key)
        setStream((l) => [...l, ev as LogEvent])
        if (ev.kind === 'change') setShownChanges((n) => Math.max(n, ev.index + 1))
        if (ev.kind === 'status' && ev.status === 'succeeded') {
          fetch(`/api/runs/${id}`)
            .then((r) => r.json())
            .then((rec: RunRecord) => setRecord(rec))
            .then(refresh)
            .catch(() => {})
        }
      } catch {
        /* ignore malformed frames */
      }
    }
    return () => es.close()
  }, [id, refresh])

  const finished = !!record && !['running', 'validating'].includes(record.status)

  useEffect(() => {
    if (finished || !record) return
    const start = record.startedAt
    const t = setInterval(() => setElapsed(Date.now() - start), 100)
    return () => clearInterval(t)
  }, [finished, record])

  // ---- pipeline state derived from the event stream -----------------------
  const pipeline = useMemo(() => derivePipeline(stream), [stream])
  const logs = useMemo(() => stream.filter((e) => ACTIVITY_KINDS.has(e.kind)), [stream])

  const byId = useMemo(() => new Map(state.versions.map((v) => [v.id, v])), [state.versions])
  const diff = useMemo<DiffRow[]>(() => {
    if (!record) return []
    const base = byId.get(record.baseVersionId)?.file
    const result = record.resultVersionId ? byId.get(record.resultVersionId)?.file : undefined
    return base && result ? diffLines(base, result) : []
  }, [record, byId])

  if (record === undefined) {
    return <div className="px-5 py-10 text-center text-[12.5px] text-ink-3">Loading run…</div>
  }
  if (record === null) {
    return <div className="px-5 py-10 text-center text-[12.5px] text-ink-3">Run not found.</div>
  }

  const fromDashboard = state.run?.id === record.id && !finished
  const changes = record.changes ?? []
  const shown = Math.min(shownChanges, changes.length)
  const duration = finished ? record.durationMs : elapsed
  const rejected = record.status === 'failed'
  const hasPipeline = pipeline.agents.length > 0
  const feed = selectedAgent ? logs.filter((e) => !e.agent || e.agent === selectedAgent) : logs

  return (
    <div>
      <Breadcrumb id={record.id} from={fromDashboard ? 'dashboard' : 'runs'} />
      <RunHeading
        status={record.status}
        batch={record.traceIds.length}
        attempts={record.attempts}
        duration={finished ? fmtDuration(record.durationMs) : `${(duration / 1000).toFixed(1)}s`}
        when={finished ? relTime(record.startedAt) : undefined}
      />

      {/* Outcome banner */}
      {finished && record.status === 'succeeded' && record.resultVersionId && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 30 }}
          className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-green/30 bg-green/6 px-4 py-3"
        >
          <span className="size-1.5 rounded-full bg-green" />
          <span className="text-[13px]">
            Committed <span className="font-mono text-green">{record.resultVersionId}</span>
            {record.commitBranch ? (
              <>
                {' '}
                on <span className="font-mono text-ink-2">{record.commitBranch}</span>
              </>
            ) : null}{' '}
            — {record.changes.length} {record.changes.length === 1 ? 'line edit' : 'line edits'} applied to{' '}
            <span className="font-mono text-ink-2">{record.baseVersionId}</span>
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Link
              to="/versions"
              className="btn-primary flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium text-white"
            >
              View version <ArrowRight size={13} />
            </Link>
            <Link to="/runs" className="btn-ghost rounded-md px-3 py-1.5 text-[12px] text-ink-2">
              All runs
            </Link>
          </div>
          {record.commitTitle && (
            <div className="w-full border-t border-green/20 pt-2 font-mono text-[12px] leading-relaxed text-ink-2">
              <span className="text-green">$ git log -1 --pretty=%s</span>
              <div className="mt-0.5">{record.commitTitle}</div>
              {record.commitBody && (
                <div className="mt-1 whitespace-pre-wrap font-sans text-[12px] text-ink-3">{record.commitBody}</div>
              )}
            </div>
          )}
        </motion.div>
      )}
      {finished && record.status === 'failed' && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 30 }}
          className="mb-4 flex items-start gap-3 rounded-lg border border-red/30 bg-red/6 px-4 py-3"
        >
          <XCircle size={14} className="mt-0.5 shrink-0 text-red" />
          <div>
            <div className="text-[13px] text-red">Run failed after {record.attempts} attempts</div>
            <div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">{record.note}</div>
          </div>
        </motion.div>
      )}
      {finished && record.status === 'no-changes' && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 30 }}
          className="mb-4 flex items-start gap-3 rounded-lg border border-line-2 bg-panel-2/60 px-4 py-3"
        >
          <CircleSlash size={14} className="mt-0.5 shrink-0 text-ink-3" />
          <div>
            <div className="text-[13px]">No edits proposed</div>
            <div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">{record.note}</div>
          </div>
        </motion.div>
      )}
      {!finished && record.status === 'succeeded' && null}

      {/* The live pipeline graph */}
      {hasPipeline && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          className="card mb-4 overflow-hidden"
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <span className="text-[13px] font-semibold">MAJICS pipeline</span>
            <div className="flex items-center gap-3 text-[11px]">
              <StageChip label="review" state={pipeline.stages.review} />
              <StageChip label="propose" state={pipeline.stages.propose} />
            </div>
          </div>
          <div className="px-3 py-2">
            <PipelineGraph
              agents={pipeline.agents}
              stages={pipeline.stages}
              reportReady={pipeline.reportReady}
              committed={record.status === 'succeeded'}
              failed={record.status === 'failed'}
              selected={selectedAgent}
              onSelect={setSelectedAgent}
            />
          </div>
        </motion.div>
      )}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_480px]">
        {/* min-w-0/minmax(0,1fr): truncating rows (tool args) must not blow
            the 1fr track out past the page via their min-content. */}
        <div className="flex min-w-0 flex-col gap-4">
          <ActivityLog
            events={feed}
            allEvents={logs}
            agents={pipeline.agents}
            selected={selectedAgent}
            onSelect={setSelectedAgent}
            live={!finished}
            stagger={finished ? 0.03 : 0}
          />

          {/* Batch */}
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-3">
              <span className="text-[13px] font-semibold">Batch</span>
              <span className="font-mono text-[11px] text-ink-3">
                {record.traceIds.length} traces · base {record.baseVersionId}
              </span>
            </div>
            <div>
              {record.traceIds.map((tid, i) => {
                const trace = state.traces.find((t) => t.id === tid)
                return (
                  <motion.div
                    key={tid}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: 0.1 + i * 0.04 }}
                  >
                    <Link
                      to={`/traces/${tid}`}
                      className="hover-row flex items-center gap-3 border-b border-line/60 px-5 py-2.5 last:border-b-0"
                    >
                      <span className="font-mono text-[12px] text-ink">{tid}</span>
                      <span className="truncate text-[12px] text-ink-3">{trace?.firstLine ?? ''}</span>
                      {trace?.feedback && <MessageSquare size={11} className="ml-auto shrink-0 text-amber" />}
                    </Link>
                  </motion.div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {/* The review judge's HTML report */}
          {(pipeline.reportReady || record.hasReport) && (
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 30 }}
              className="card overflow-hidden"
            >
              <div className="flex items-center justify-between border-b border-line px-5 py-3">
                <span className="flex items-center gap-2 text-[13px] font-semibold">
                  <ScrollText size={14} className="text-amber" /> Review report
                </span>
                <a
                  href={`/api/runs/${id}/report`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-ghost rounded-md px-2 py-1 text-[11px] text-ink-2"
                >
                  open ↗
                </a>
              </div>
              <iframe
                title="Trace Review Report"
                src={`/api/runs/${id}/report`}
                sandbox=""
                className="h-[560px] w-full bg-[#08090b]"
              />
            </motion.div>
          )}

          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-3">
              <span className="text-[13px] font-semibold">{rejected ? 'Rejected changes' : 'Proposed changes'}</span>
              <span className="font-mono text-[11px] text-ink-3">
                {shown} / {changes.length}
              </span>
            </div>
            <div className="flex flex-col gap-3 p-3">
              {changes.length === 0 ? (
                finished ? (
                  <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                    <CircleSlash size={18} className="text-ink-3" />
                    <span className="text-[12.5px] text-ink-2">The pipeline returned an empty edit list.</span>
                    <span className="max-w-[280px] text-[11.5px] leading-relaxed text-ink-3">
                      The batch was marked analyzed and AGENTS.md was left untouched.
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 px-2 py-3">
                    {[100, 88, 56].map((w) => (
                      <div key={w} className="h-2.5 animate-pulse rounded bg-white/5" style={{ width: `${w}%` }} />
                    ))}
                  </div>
                )
              ) : (
                <AnimatePresence initial={false}>
                  {changes.slice(0, shown).map((c, i) => (
                    <ChangeCard key={i} change={c} index={i} muted={rejected} />
                  ))}
                </AnimatePresence>
              )}
            </div>
          </div>

          {diff.length > 0 && <CombinedDiff diff={diff} animate={!finished} />}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------- pipeline state */

function derivePipeline(events: LogEvent[]) {
  const roster = new Map<string, PipelineAgent>()
  const states = new Map<string, AgentState>()
  const stages: StageStates = {}
  let reportReady = false
  for (const ev of events) {
    if (ev.kind === 'pipeline' && ev.agents) {
      for (const a of ev.agents) roster.set(a.key, a)
    } else if (ev.kind === 'agent_start' && ev.agent) {
      const base = roster.get(ev.agent)
      if (base) {
        states.set(ev.agent, { ...base, status: 'working' })
      }
    } else if (ev.kind === 'agent_end' && ev.agent) {
      const base = roster.get(ev.agent)
      if (base) {
        states.set(ev.agent, {
          ...base,
          status: ev.status === 'done' ? 'done' : 'error',
          durationMs: ev.durationMs,
          error: ev.error,
          usage: ev.usage,
        })
      }
    } else if (ev.kind === 'stage' && ev.stage) {
      stages[ev.stage as 'review' | 'propose'] = ev.status === 'end' ? 'end' : 'start'
    } else if (ev.kind === 'report') {
      reportReady = true
    }
  }
  const agents: AgentState[] = [...roster.values()].map(
    (a) => states.get(a.key) ?? { ...a, status: 'pending' as const },
  )
  return { agents, stages, reportReady }
}

function StageChip({ label, state }: { label: string; state?: 'start' | 'end' }) {
  const cls = !state
    ? 'border-line text-ink-3'
    : state === 'start'
      ? 'border-accent/40 bg-accent/10 text-[#8b95f6]'
      : 'border-green/30 bg-green/10 text-green'
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${cls}`}>
      {state === 'start' ? label + ' · live' : state === 'end' ? label + ' · done' : label}
    </span>
  )
}

/* ------------------------------------------------------------------ shared */

/** A tool call merged with its result: `tool` and `tool_result` events pair up
 * by (agent, name) in arrival order; a call without a result yet is still
 * running. */
interface ToolRowData {
  name: string
  args: string
  agent?: string
  result?: string
  failed?: boolean
  done?: boolean
  at: number
}

type FeedRow =
  | { type: 'log' | 'feedback' | 'agent' | 'commit' | 'message' | 'proposal' | 'agent_start' | 'agent_end' | 'stage' | 'report' | 'analytics'; ev: LogEvent }
  | ({ type: 'tool' } & ToolRowData)

function buildFeed(events: LogEvent[]): FeedRow[] {
  const rows: FeedRow[] = []
  const pending = new Map<string, number[]>()
  const keyOf = (ev: LogEvent) => `${ev.agent ?? ''}:${ev.name ?? 'tool'}`
  for (const ev of events) {
    if (ev.kind === 'tool') {
      const key = keyOf(ev)
      pending.set(key, [...(pending.get(key) ?? []), rows.length])
      rows.push({ type: 'tool', name: ev.name ?? 'tool', args: ev.detail ?? '', agent: ev.agent, at: ev.at })
    } else if (ev.kind === 'tool_result') {
      const key = keyOf(ev)
      const queue = pending.get(key)
      const idx = queue?.shift()
      if (idx !== undefined) {
        const row = rows[idx] as Extract<FeedRow, { type: 'tool' }>
        row.failed = ev.detail?.startsWith('failed') || ev.detail?.includes('failed:')
        row.done = true
        if (ev.detail && !row.failed) row.result = ev.detail
      }
    } else {
      rows.push({ type: ev.kind, ev } as Extract<FeedRow, { ev: LogEvent }>)
    }
  }
  return rows
}

/** One-line argument preview: `{"path":"agents.md"}` → `path=agents.md`. */
function argsPreview(detail: string): string {
  if (!detail) return ''
  try {
    const parsed = JSON.parse(detail)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return Object.entries(parsed)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
        .join(' ')
    }
  } catch {
    /* raw text args */
  }
  return detail
}

function ActivityLog({
  events,
  allEvents,
  agents,
  selected,
  onSelect,
  live,
  stagger = 0,
}: {
  events: LogEvent[]
  allEvents: LogEvent[]
  agents: AgentState[]
  selected: string | null
  onSelect: (key: string | null) => void
  live?: boolean
  stagger?: number
}) {
  const rows = useMemo(() => buildFeed(events), [events])
  const colorOf = (key?: string) => agents.find((a) => a.key === key)?.color
  const agentOf = (key?: string) => agents.find((a) => a.key === key)
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="mr-1 text-[13px] font-semibold">Activity</span>
        {/* Agent toggles: each chip is one pipeline agent's live trace */}
        {agents.length > 0 && (
          <>
            <button
              onClick={() => onSelect(null)}
              className={`rounded-full border px-2 py-0.5 font-mono text-[10.5px] transition-colors ${
                selected === null ? 'border-accent/50 bg-accent/15 text-[#8b95f6]' : 'border-line-2 text-ink-3 hover:text-ink-2'
              }`}
            >
              all
            </button>
            {agents.map((a) => (
              <button
                key={a.key}
                onClick={() => onSelect(selected === a.key ? null : a.key)}
                title={`${a.key} · ${a.model}`}
                className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10.5px] transition-colors ${
                  selected === a.key ? 'border-accent/50 bg-accent/15 text-ink' : 'border-line-2 text-ink-3 hover:text-ink-2'
                }`}
              >
                <span
                  className={`size-1.5 rounded-full ${a.status === 'working' ? 'pulse-dot' : ''}`}
                  style={{ background: a.status === 'error' ? '#f2555a' : a.status === 'done' ? '#3dd68c' : a.color }}
                />
                {a.key}
                <span className="text-ink-3/70">{a.model.split('/').pop()}</span>
              </button>
            ))}
          </>
        )}
        <span className="ml-auto font-mono text-[10.5px] text-ink-3">
          {allEvents.length} events{selected ? ` · ${agentOf(selected)?.model}` : ''}
        </span>
      </div>
      <div className="flex max-h-[640px] flex-col overflow-y-auto px-2 py-2">
        <AnimatePresence initial={false}>
          {rows.map((row, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 380, damping: 30, delay: i * stagger }}
              className="relative flex items-start gap-3 px-3 py-2"
            >
              {i < rows.length - 1 && <span className="absolute top-8 left-[22.5px] h-[calc(100%-18px)] w-px bg-line" />}
              {row.type === 'tool' ? (
                <FeedToolRow row={row} color={colorOf(row.agent)} />
              ) : row.type === 'feedback' ? (
                <FeedFeedbackRow ev={row.ev} />
              ) : row.type === 'commit' ? (
                <FeedCommitRow ev={row.ev} />
              ) : row.type === 'message' ? (
                <FeedMessageRow ev={row.ev} color={colorOf(row.ev.agent)} agent={agentOf(row.ev.agent)} />
              ) : row.type === 'proposal' ? (
                <FeedProposalRow ev={row.ev} color={colorOf(row.ev.agent)} />
              ) : row.type === 'agent_start' ? (
                <FeedAgentLifecycleRow ev={row.ev} color={colorOf(row.ev.agent)} start />
              ) : row.type === 'agent_end' ? (
                <FeedAgentLifecycleRow ev={row.ev} color={colorOf(row.ev.agent)} />
              ) : row.type === 'stage' ? (
                <FeedStageRow ev={row.ev} />
              ) : row.type === 'report' ? (
                <FeedReportRow ev={row.ev} />
              ) : row.type === 'agent' ? (
                <FeedAgentRow ev={row.ev} />
              ) : (
                <FeedLogRow ev={row.ev} />
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        {live && (
          <div className="flex items-center gap-3 px-3 py-2.5">
            <span className="grid size-6 place-items-center">
              <span className="pulse-dot size-1.5 rounded-full bg-[#8b95f6]" />
            </span>
            <span className="text-[12px] text-ink-3">pipeline working…</span>
          </div>
        )}
      </div>
    </div>
  )
}

function At({ at }: { at: number }) {
  return <span className="ml-auto pt-0.5 font-mono text-[10.5px] text-ink-3 tabular-nums">+{(at / 1000).toFixed(1)}s</span>
}

function AgentTag({ agentKey, color }: { agentKey?: string; color?: string }) {
  if (!agentKey) return null
  return (
    <span className="flex shrink-0 items-center gap-1.5 pr-1 font-mono text-[10px] text-ink-3">
      <span className="size-1.5 rounded-full" style={{ background: color ?? '#5f6670' }} />
      {agentKey}
    </span>
  )
}

function FeedLogRow({ ev }: { ev: LogEvent }) {
  const Icon = ev.icon ? (icons[ev.icon] ?? FileText) : FileText
  return (
    <>
      <span className={`grid size-6 shrink-0 place-items-center rounded-md border ${ev.level ? levelStyles[ev.level] : 'border-line bg-panel-2 text-ink-2'}`}>
        <Icon size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className={`text-[12.5px] ${ev.level === 'error' ? 'text-red' : 'text-ink'}`}>{ev.text}</div>
        {ev.detail && <div className="mt-0.5 font-mono text-[11px] text-ink-3">{ev.detail}</div>}
      </div>
      <At at={ev.at} />
    </>
  )
}

function FeedAgentRow({ ev }: { ev: LogEvent }) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-line bg-panel-2 text-ink-3">
        <Bot size={12} />
      </span>
      <div className="min-w-0 pt-1 text-[12px] text-ink-3">{ev.text}</div>
      <At at={ev.at} />
    </>
  )
}

/** MAJICS's live narrative — reading traces and judging the signal. */
function FeedFeedbackRow({ ev }: { ev: LogEvent }) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-amber/30 bg-amber/10 text-amber">
        <Lightbulb size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="text-[12.5px] font-medium text-ink">{ev.text}</div>
        {ev.detail && <div className="mt-0.5 text-[11.5px] leading-relaxed text-ink-3">{ev.detail}</div>}
      </div>
      <At at={ev.at} />
    </>
  )
}

/** The commit the MAJICS judge authored — shown as it happens. */
function FeedCommitRow({ ev }: { ev: LogEvent }) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-green/30 bg-green/10 text-green">
        <GitBranch size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="font-mono text-[12px] text-ink">{ev.title}</div>
        {ev.body && <div className="mt-0.5 whitespace-pre-wrap text-[11.5px] leading-relaxed text-ink-3">{ev.body}</div>}
      </div>
      <At at={ev.at} />
    </>
  )
}

/** One agent's finished turn text — an analysis, an ask_panel answer, a verdict. */
function FeedMessageRow({
  ev,
  color,
  agent,
}: {
  ev: LogEvent
  color?: string
  agent?: AgentState
}) {
  const [open, setOpen] = useState(false)
  const text = ev.text ?? ''
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-line bg-panel-2 text-ink-2">
        <MessageSquare size={12} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <button onClick={() => setOpen(!open)} className="hover-row -my-1 flex w-full items-center gap-2 rounded-md py-1.5 pr-1 text-left">
          <AgentTag agentKey={ev.agent} color={color} />
          <span className="truncate text-[12px] text-ink-2">
            {text.split('\n')[0].slice(0, 120) || '(empty message)'}
          </span>
          <span className="ml-auto flex shrink-0 items-center gap-2">
            {agent?.status === 'working' && <span className="pulse-dot size-1.5 rounded-full bg-[#8b95f6]" />}
            <motion.span animate={{ rotate: open ? 90 : 0 }} className="text-ink-3">
              <ChevronRight size={13} />
            </motion.span>
          </span>
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="mt-1 max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-black/25 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-ink-2">
                {text}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <At at={ev.at} />
    </>
  )
}

/** A proposer's submitted edit set. */
function FeedProposalRow({ ev, color }: { ev: LogEvent; color?: string }) {
  const [open, setOpen] = useState(false)
  const edits = ev.edits ?? []
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-[#b06ee8]/35 bg-[#b06ee8]/10 text-[#b06ee8]">
        <Layers size={12} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <button onClick={() => setOpen(!open)} className="hover-row -my-1 flex w-full min-w-0 items-center gap-2 rounded-md py-1.5 pr-1 text-left">
          <AgentTag agentKey={ev.agent} color={color} />
          <span className="text-[12.5px] text-ink">
            proposed <span className="font-mono text-ink-2">{ev.count ?? edits.length}</span>{' '}
            {(ev.count ?? edits.length) === 1 ? 'edit' : 'edits'}
          </span>
          {ev.note && <span className="truncate text-[11.5px] text-ink-3">— {ev.note}</span>}
          <motion.span animate={{ rotate: open ? 90 : 0 }} className="ml-auto shrink-0 text-ink-3">
            <ChevronRight size={13} />
          </motion.span>
        </button>
        <AnimatePresence initial={false}>
          {open && edits.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="mt-1 flex flex-col gap-2">
                {edits.map((e, i) => (
                  <div key={i} className="rounded-md border border-line bg-black/25 px-3 py-2">
                    <div className="font-mono text-[10.5px] text-ink-3">edit {i + 1}</div>
                    {e.oldText && <div className="mt-1 break-all font-mono text-[11px] text-red/85">− {e.oldText}</div>}
                    {e.newText && <div className="mt-0.5 break-all font-mono text-[11px] text-green">+ {e.newText}</div>}
                    <div className="mt-1.5 text-[11px] leading-relaxed text-ink-3">{e.rationale}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {e.evidence.map((id) => (
                        <Link
                          key={id}
                          to={`/traces/${id}`}
                          className="btn-ghost rounded px-1.5 py-px font-mono text-[10px] text-[#8b95f6]"
                        >
                          {id}
                        </Link>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <At at={ev.at} />
    </>
  )
}

function FeedAgentLifecycleRow({ ev, color, start }: { ev: LogEvent; color?: string; start?: boolean }) {
  const ok = ev.status !== 'error'
  return (
    <>
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-md border ${
          start ? 'border-line bg-panel-2 text-ink-2' : ok ? 'border-green/30 bg-green/10 text-green' : 'border-red/30 bg-red/10 text-red'
        }`}
      >
        <Bot size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="flex items-center gap-2">
          <AgentTag agentKey={ev.agent} color={color} />
          <span className="text-[12.5px] text-ink">
            {ev.agent} <span className="font-mono text-[11px] text-ink-3">{ev.model}</span>{' '}
            {start ? 'started' : ok ? `finished in ${((ev.durationMs ?? 0) / 1000).toFixed(1)}s` : 'failed'}
          </span>
          {ev.usage && (
            <span className="font-mono text-[10px] text-ink-3">
              {ev.usage.prompt_tokens ?? 0}→{ev.usage.completion_tokens ?? 0} tok
            </span>
          )}
        </div>
        {ev.error && <div className="mt-0.5 font-mono text-[11px] text-red/85">{ev.error}</div>}
      </div>
      <At at={ev.at} />
    </>
  )
}

function FeedStageRow({ ev }: { ev: LogEvent }) {
  const start = ev.status !== 'end'
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-accent/30 bg-accent/10 text-[#8b95f6]">
        <Gavel size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <span className="text-[12.5px] font-medium uppercase tracking-wide text-ink">
          {ev.stage} stage {start ? 'started' : 'done'}
        </span>
        {ev.durationMs != null && (
          <span className="ml-2 font-mono text-[11px] text-ink-3">{(ev.durationMs / 1000).toFixed(1)}s</span>
        )}
      </div>
      <At at={ev.at} />
    </>
  )
}

function FeedReportRow({ ev }: { ev: LogEvent }) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-amber/30 bg-amber/10 text-amber">
        <ScrollText size={12} />
      </span>
      <div className="min-w-0 pt-0.5">
        <span className="text-[12.5px] text-ink">Review report ready</span>
        {ev.title && <span className="ml-2 text-[12px] text-ink-2">{ev.title}</span>}
        <span className="ml-2 font-mono text-[10.5px] text-ink-3">{((ev.bytes ?? 0) / 1024).toFixed(1)} kB</span>
      </div>
      <At at={ev.at} />
    </>
  )
}

function FeedToolRow({ row, color }: { row: ToolRowData; color?: string }) {
  const [open, setOpen] = useState(false)
  const running = row.result === undefined && !row.failed && !row.done
  return (
    <>
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-md border ${
          row.failed ? 'border-red/30 bg-red/10 text-red' : 'border-line bg-panel-2 text-ink-2'
        }`}
      >
        <Wrench size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <button
          onClick={() => setOpen(!open)}
          className="hover-row -my-1 flex w-full min-w-0 items-center gap-2.5 rounded-md py-1.5 pr-1 text-left"
        >
          <AgentTag agentKey={row.agent} color={color} />
          <span className="shrink-0 font-mono text-[12px] text-ink-2">{row.name}</span>
          <span className="truncate font-mono text-[11px] text-ink-3">{argsPreview(row.args)}</span>
          <span className="ml-auto flex shrink-0 items-center gap-2 pr-1">
            {row.failed ? (
              <XCircle size={12} className="text-red" />
            ) : running ? (
              <span className="pulse-dot size-1.5 rounded-full bg-[#8b95f6]" />
            ) : row.result ? (
              <motion.span animate={{ rotate: open ? 90 : 0 }} className="text-ink-3">
                <ChevronRight size={13} />
              </motion.span>
            ) : null}
          </span>
        </button>
        <AnimatePresence initial={false}>
          {open && row.result && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="mt-1 break-words rounded-md bg-black/25 px-3 py-2.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
                {row.result}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <At at={row.at} />
    </>
  )
}

function Breadcrumb({ id, from }: { id: string; from: 'dashboard' | 'runs' }) {
  return (
    <nav className="mb-5 flex items-center gap-1.5 text-[12.5px] text-ink-3">
      <Link to={from === 'runs' ? '/runs' : '/'} className="hover:text-ink-2">
        {from === 'runs' ? 'Runs' : 'Dashboard'}
      </Link>
      <ChevronRight size={13} />
      <span className="font-mono text-[12px] text-ink-2">run {id}</span>
    </nav>
  )
}

function RunHeading({
  status,
  batch,
  attempts,
  duration,
  when,
}: {
  status: string
  batch: number
  attempts: number
  duration: string
  when?: string
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="text-[17px] font-semibold tracking-tight">Optimization run</h1>
      <Badge kind={status}>{status === 'no-changes' ? 'no changes' : status}</Badge>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-ink-3 md:ml-auto">
        {when && (
          <span>
            started <span className="text-ink-2">{when}</span>
          </span>
        )}
        <span>
          batch <span className="font-mono text-ink-2">{batch} traces</span>
        </span>
        <span>
          attempt <span className="font-mono text-ink-2">{attempts}</span>
        </span>
        <span>
          elapsed <span className="font-mono text-ink-2 tabular-nums">{duration}</span>
        </span>
      </div>
    </div>
  )
}

function ChangeCard({ change: c, index, muted }: { change: ProposedChange; index: number; muted?: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 320, damping: 28 }}
      className={`rounded-lg border border-line bg-panel-2/50 p-3 ${muted ? 'opacity-75' : ''}`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-flex rounded-[5px] border px-1.5 py-px text-[10.5px] font-medium ${opStyles[c.op]}`}>
          {c.op}
        </span>
        <span className="font-mono text-[11.5px] text-ink-2">
          {c.section} · L{c.line}
        </span>
        <span className="ml-auto font-mono text-[10.5px] text-ink-3">#{index + 1}</span>
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-ink-2">{c.rationale}</p>
      <div className="mt-2.5 overflow-x-auto rounded-md bg-black/30 px-3 py-2 font-mono text-[11.5px] leading-[1.7]">
        {c.before && (
          <div className="flex gap-2 text-red/85">
            <span className="select-none">−</span>
            <span className="line-through whitespace-pre-wrap">{c.before}</span>
          </div>
        )}
        {c.after && (
          <div className="flex gap-2 text-green">
            <span className="select-none">+</span>
            <span className="whitespace-pre-wrap">{c.after}</span>
          </div>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span className="label mr-1">Evidence</span>
        {c.evidence.map((id) => (
          <Link
            key={id}
            to={`/traces/${id}`}
            className="btn-ghost inline-flex rounded-md px-1.5 py-0.5 font-mono text-[10.5px] text-[#8b95f6]"
          >
            {id}
          </Link>
        ))}
      </div>
    </motion.div>
  )
}

function CombinedDiff({ diff, animate = true }: { diff: DiffRow[]; animate?: boolean }) {
  const adds = diff.filter((r) => r.type === 'add').length
  const dels = diff.filter((r) => r.type === 'del').length
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 30 }}
      className="card overflow-hidden"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <span className="text-[13px] font-semibold">Combined diff</span>
        <span className="font-mono text-[11px]">
          <span className="text-green">+{adds}</span> <span className="text-red">−{dels}</span>
        </span>
      </div>
      <div className="overflow-x-auto py-2 font-mono text-[11.5px] leading-[1.7]">
        {diff.map((row, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: animate ? i * 0.03 : 0, duration: 0.25 }}
            className={`flex gap-3 px-4 ${
              row.type === 'add'
                ? 'bg-green/8 text-green'
                : row.type === 'del'
                  ? 'bg-red/8 text-red/85 line-through'
                  : 'text-ink-3'
            }`}
          >
            <span className="w-5 shrink-0 text-right text-ink-3/60 select-none">{row.b ?? ''}</span>
            <span className="w-3 shrink-0 select-none">
              {row.type === 'add' ? '+' : row.type === 'del' ? '−' : ''}
            </span>
            <span className="whitespace-pre-wrap">{row.text || ' '}</span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}
