import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { Minus, Plus, MessageSquare, ArrowRight } from 'lucide-react'
import { useStore, relTime, actions } from '../store'
import type { Trace, RunRecord } from '../data'
import { Badge, CountUp, Sparkline, StatCard } from '../components/ui'
import { BatchRing } from '../components/BatchRing'

const filters = ['All', 'New', 'Analyzed', 'Feedback'] as const
type Filter = (typeof filters)[number]

const gridCols = 'grid grid-cols-[minmax(0,1fr)_72px_88px] md:grid-cols-[1fr_90px_60px_300px_100px]'

export function Dashboard() {
  const { state, refresh } = useStore()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('All')
  const [lastRun, setLastRun] = useState<RunRecord | null | undefined>(undefined)
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/runs')
      .then((r) => r.json())
      .then((runs: RunRecord[]) => {
        if (!cancelled) setLastRun(runs[0] ?? null)
      })
      .catch(() => !cancelled && setLastRun(null))
    return () => {
      cancelled = true
    }
  }, [state.run])

  const unanalyzed = state.traces.filter((t) => t.status === 'new').length
  const runActive = state.run && state.run.status !== 'succeeded'

  const visible = state.traces.filter((t) => {
    if (filter === 'New') return t.status === 'new'
    if (filter === 'Analyzed') return t.status === 'analyzed'
    if (filter === 'Feedback') return !!t.feedback
    return true
  })

  const startRun = async () => {
    setStartError(null)
    try {
      const { id } = await actions.startRun()
      navigate(`/runs/${id}`)
    } catch (err) {
      setStartError(err instanceof Error ? err.message.replace(/^\d+\s*/, '') : 'could not start the run')
    }
  }

  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
      className="flex flex-col gap-4"
    >
      {/* Stat row */}
      <motion.div variants={rise} className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 lg:grid-cols-4 lg:gap-4">
        <StatCard label="Unanalyzed traces">
          <CountUp value={unanalyzed} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 text-[12px] text-ink-3">of {state.batchSize} for next batch</span>
        </StatCard>
        <StatCard label="Total traces" extra={<Sparkline points={traceHistogram(state.traces)} />}>
          <CountUp value={state.traces.length} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 text-[12px] text-ink-3">last 24h</span>
        </StatCard>
        <StatCard label="Versions">
          <CountUp value={state.versions.length} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 font-mono text-[11px] text-ink-3">
            current {state.currentId} · {state.currentBranch ?? 'detached'}
          </span>
        </StatCard>
        <StatCard label="Last run" to={lastRun ? `/runs/${lastRun.id}` : undefined}>
          {lastRun ? (
            <div className="flex flex-wrap items-center gap-2 pb-[5px]">
              <Badge kind={lastRun.status} />
              <span className="text-[12px] text-ink-3">{relTime(lastRun.startedAt)}</span>
              <span className="font-mono text-[11px] text-ink-3">{lastRun.id}</span>
            </div>
          ) : (
            <span className="pb-[5px] font-mono text-[12px] text-ink-3">—</span>
          )}
        </StatCard>
      </motion.div>

      {/* Batch panel */}
      <motion.div variants={rise} className="card flex flex-col items-start gap-6 px-5 py-5 md:flex-row md:items-center md:gap-8 md:px-7">
        <div className="self-center md:self-auto">
          <BatchRing filled={unanalyzed} total={state.batchSize} />
        </div>
        <div className="flex flex-col gap-3">
          <div>
            <div className="text-[14px] font-semibold">Batch</div>
            <div className="mt-0.5 max-w-[300px] text-[12.5px] leading-relaxed text-ink-2">
              Each optimization mines one batch of unanalyzed traces and proposes line edits to AGENTS.md.
            </div>
          </div>
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-1.5">
              <StepBtn onClick={() => actions.setBatchSize(state.batchSize - 1).then(refresh)}>
                <Minus size={12} />
              </StepBtn>
              <BatchSizeInput value={state.batchSize} onCommit={(v) => actions.setBatchSize(v).then(refresh)} />
              <StepBtn onClick={() => actions.setBatchSize(state.batchSize + 1).then(refresh)}>
                <Plus size={12} />
              </StepBtn>
              <span className="ml-1 text-[12px] text-ink-3">batch size</span>
            </div>
            <button
              onClick={() => actions.toggleAuto(!state.autoOptimize).then(refresh)}
              className="flex items-center gap-2 text-[12px] text-ink-2"
            >
              <span
                className={`flex h-[18px] w-8 items-center rounded-full border px-[2px] transition-colors ${
                  state.autoOptimize ? 'justify-end border-accent bg-accent' : 'justify-start border-line-2 bg-panel-2'
                }`}
              >
                <motion.span layout transition={{ type: 'spring', stiffness: 600, damping: 32 }} className="size-3 rounded-full bg-white/90" />
              </span>
              Auto-optimize
            </button>
          </div>
        </div>
        <div className="w-full md:ml-auto md:w-auto">
          {runActive ? (
            <Link
              to={`/runs/${state.run!.id}`}
              className="btn-ghost flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-[13px] font-medium text-accent-2 md:w-auto"
            >
              <span className="pulse-dot size-1.5 rounded-full bg-accent-2" />
              View running optimization
              <ArrowRight size={14} />
            </Link>
          ) : (
            <div className="w-full md:w-auto">
              <motion.button
                onClick={startRun}
                whileTap={{ scale: 0.985 }}
                className="btn-primary flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-[13px] font-medium text-white md:w-auto"
              >
                Start optimization
                <ArrowRight size={14} />
              </motion.button>
              <AnimatePresence>
                {startError && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="mt-2 rounded-md border border-red/30 bg-red/8 px-2.5 py-1.5 text-left text-[11.5px] text-red"
                  >
                    {startError}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </motion.div>

      {/* Traces table */}
      <motion.div variants={rise} className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2.5">
            <span className="text-[13px] font-semibold">Traces</span>
            <span className="rounded-full bg-ink/5 px-1.5 py-px font-mono text-[10.5px] text-ink-3">
              {visible.length}
            </span>
          </div>
          <div className="flex items-center gap-0.5">
            {filters.map((f) => (
              <button key={f} onClick={() => setFilter(f)} className="relative rounded-md px-2.5 py-1 text-[12px]">
                {filter === f && (
                  <motion.span
                    layoutId="filter-pill"
                    className="absolute inset-0 rounded-md bg-ink/6"
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <span className={`relative ${filter === f ? 'text-ink' : 'text-ink-3 hover:text-ink-2'}`}>{f}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={`${gridCols} gap-3 border-b border-line px-4 py-2 sm:px-5`}>
          <span className="label">Session</span>
          <span className="label">Received</span>
          <span className="label hidden md:block">Turns</span>
          <span className="label hidden md:block">Feedback</span>
          <span className="label">Status</span>
        </div>

        <AnimatePresence initial={false}>
          {visible.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: -14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: 'spring', stiffness: 400, damping: 34 }}
            >
              <Link
                to={`/traces/${t.id}`}
                className={`hover-row ${gridCols} items-center gap-3 border-b border-line/60 px-4 py-2.5 sm:px-5 ${
                  state.arrivedIds.includes(t.id) ? 'row-flash' : ''
                }`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-mono text-[12px] text-ink">{t.id}</span>
                    {t.feedback && <MessageSquare size={11} className="shrink-0 text-amber md:hidden" />}
                  </div>
                  <div className="truncate text-[12px] text-ink-3">{t.firstLine}</div>
                </div>
                <span className="text-[12px] text-ink-2">{relTime(t.receivedAt)}</span>
                <span className="hidden font-mono text-[12px] text-ink-2 md:block">{t.turns}</span>
                <span className="hidden min-w-0 items-center gap-1.5 text-[12px] md:flex">
                  {t.feedback ? (
                    <>
                      <MessageSquare size={12} className="shrink-0 text-amber" />
                      <span className="truncate text-amber/90">{t.feedback}</span>
                    </>
                  ) : (
                    <span className="text-ink-3">—</span>
                  )}
                </span>
                <span>
                  <Badge kind={t.status} />
                </span>
              </Link>
            </motion.div>
          ))}
        </AnimatePresence>
        {visible.length === 0 && (
          <div className="px-5 py-10 text-center text-[12.5px] text-ink-3">No traces match this filter.</div>
        )}
      </motion.div>
    </motion.div>
  )
}

const rise = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 320, damping: 30 } },
}

/** Nine buckets over the last 24h of trace arrivals. */
function traceHistogram(traces: Trace[]): number[] {
  const now = Date.now()
  const window = 24 * 60 * 60 * 1000
  const buckets = new Array(9).fill(0)
  for (const t of traces) {
    const age = now - t.receivedAt
    if (age > window) continue
    const idx = Math.min(8, Math.floor(((window - age) / window) * 9))
    buckets[idx]++
  }
  return buckets
}

function StepBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="btn-ghost grid size-6 place-items-center rounded-md text-ink-2">
      {children}
    </button>
  )
}

function BatchSizeInput({ value, onCommit }: { value: number; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState(String(value))

  // Steppers and other sources update the store; mirror it into the field.
  const [prev, setPrev] = useState(value)
  if (prev !== value) {
    setPrev(value)
    setDraft(String(value))
  }

  const commit = () => {
    const parsed = parseInt(draft, 10)
    if (Number.isNaN(parsed)) {
      setDraft(String(value))
      return
    }
    const clamped = Math.max(1, Math.min(64, parsed))
    onCommit(clamped)
    setDraft(String(clamped))
  }

  return (
    <input
      type="text"
      inputMode="numeric"
      value={draft}
      onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ''))}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') {
          setDraft(String(value))
          e.currentTarget.blur()
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          onCommit(Math.min(64, value + 1))
        }
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          onCommit(Math.max(1, value - 1))
        }
      }}
      onFocus={(e) => e.currentTarget.select()}
      aria-label="Batch size"
      className="h-6 w-12 rounded-md border border-transparent bg-transparent text-center font-mono text-[13px] text-ink transition-colors outline-none hover:border-line-2 focus:border-accent focus:bg-panel-2"
    />
  )
}
