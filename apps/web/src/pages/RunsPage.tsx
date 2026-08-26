import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { Zap, Hand, ArrowRight } from 'lucide-react'
import { useStore, relTime, fmtDuration } from '../store'
import type { RunRecord } from '../data'
import { diffLines } from '../lib/diff'
import { Badge, StatCard, CountUp } from '../components/ui'

const filters = ['All', 'Succeeded', 'Failed', 'No changes'] as const
type Filter = (typeof filters)[number]

const gridCols =
  'grid grid-cols-[minmax(0,1fr)_78px_92px] md:grid-cols-[1fr_96px_84px_66px_86px_104px_100px]'

export function RunsPage() {
  const { state } = useStore()
  const [filter, setFilter] = useState<Filter>('All')
  const [rows, setRows] = useState<RunRecord[]>([])

  useEffect(() => {
    let cancelled = false
    const load = () =>
      fetch('/api/runs')
        .then((r) => r.json())
        .then((runs: RunRecord[]) => !cancelled && setRows(runs))
        .catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [state.run])

  const byId = useMemo(() => new Map(state.versions.map((v) => [v.id, v])), [state.versions])

  /** Applied line delta, read off the two version files the run sits between. */
  const delta = (r: RunRecord) => {
    const base = byId.get(r.baseVersionId)
    const result = r.resultVersionId ? byId.get(r.resultVersionId) : undefined
    if (!base || !result) return null
    const d = diffLines(base.file, result.file)
    return { adds: d.filter((x) => x.type === 'add').length, dels: d.filter((x) => x.type === 'del').length }
  }

  const visible = rows.filter((r) => {
    if (filter === 'Succeeded') return r.status === 'succeeded'
    if (filter === 'Failed') return r.status === 'failed'
    if (filter === 'No changes') return r.status === 'no-changes'
    return true
  })

  const succeeded = rows.filter((r) => r.status === 'succeeded')
  const edits = succeeded.reduce((n, r) => n + r.changes.length, 0)
  const avgEdits = succeeded.length ? edits / succeeded.length : 0
  const avgMs = rows.length ? rows.reduce((n, r) => n + r.durationMs, 0) / rows.length : 0

  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
      className="flex flex-col gap-4"
    >
      <motion.div variants={rise} className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 lg:gap-4">
        <StatCard label="Runs">
          <CountUp value={rows.length} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 text-[12px] text-ink-3">last 24h</span>
        </StatCard>
        <StatCard label="Versions created">
          <CountUp value={succeeded.length} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 text-[12px] text-ink-3">
            {rows.length ? Math.round((succeeded.length / rows.length) * 100) : 0}% of runs
          </span>
        </StatCard>
        <StatCard label="Line edits applied">
          <CountUp value={edits} className="text-[26px] font-semibold tracking-tight" />
          <span className="mb-1 text-[12px] text-ink-3">across all runs</span>
        </StatCard>
        <StatCard label="Avg edits applied">
          <span className="text-[26px] font-semibold tracking-tight tabular-nums">{avgEdits.toFixed(1)}</span>
          <span className="mb-1 text-[12px] text-ink-3">per successful run</span>
        </StatCard>
        <StatCard label="Avg duration">
          <span className="text-[26px] font-semibold tracking-tight tabular-nums">{fmtDuration(avgMs)}</span>
          <span className="mb-1 text-[12px] text-ink-3">per run</span>
        </StatCard>
      </motion.div>

      <motion.div variants={rise} className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2.5">
            <span className="text-[13px] font-semibold">Optimization runs</span>
            <span className="rounded-full bg-white/5 px-1.5 py-px font-mono text-[10.5px] text-ink-3">
              {visible.length}
            </span>
          </div>
          <div className="flex items-center gap-0.5">
            {filters.map((f) => (
              <button key={f} onClick={() => setFilter(f)} className="relative rounded-md px-2.5 py-1 text-[12px]">
                {filter === f && (
                  <motion.span
                    layoutId="runs-filter-pill"
                    className="absolute inset-0 rounded-md bg-white/6"
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <span className={`relative ${filter === f ? 'text-ink' : 'text-ink-3 hover:text-ink-2'}`}>{f}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={`${gridCols} gap-3 border-b border-line px-4 py-2 sm:px-5`}>
          <span className="label">Run</span>
          <span className="label">Started</span>
          <span className="label hidden md:block">Duration</span>
          <span className="label hidden md:block">Traces</span>
          <span className="label hidden md:block">Edits</span>
          <span className="label hidden md:block">Version</span>
          <span className="label">Status</span>
        </div>

        <AnimatePresence initial={false}>
          {visible.map((r) => {
            const d = delta(r)
            return (
              <motion.div
                key={r.id}
                layout
                initial={{ opacity: 0, y: -12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ type: 'spring', stiffness: 400, damping: 34 }}
              >
                <Link
                  to={`/runs/${r.id}`}
                  className={`hover-row group ${gridCols} items-center gap-3 border-b border-line/60 px-4 py-2.5 last:border-b-0 sm:px-5`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-[12px] text-ink">{r.id}</span>
                      {r.attempts > 1 && (
                        <span className="rounded-[4px] border border-line-2 px-1 font-mono text-[10px] text-ink-3">
                          {r.attempts} attempts
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-3">
                      {r.trigger === 'auto' ? <Zap size={10} /> : <Hand size={10} />}
                      <span className="truncate">
                        {r.trigger} · {r.model} · base <span className="font-mono">{r.baseVersionId}</span>
                      </span>
                    </div>
                  </div>
                  <span className="text-[12px] text-ink-2">{relTime(r.startedAt)}</span>
                  <span className="hidden font-mono text-[12px] text-ink-2 tabular-nums md:block">
                    {fmtDuration(r.durationMs)}
                  </span>
                  <span className="hidden font-mono text-[12px] text-ink-2 md:block">{r.traceIds.length}</span>
                  <span className="hidden font-mono text-[12px] md:block">
                    {d ? (
                      <>
                        <span className="text-green">+{d.adds}</span> <span className="text-red">−{d.dels}</span>
                      </>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </span>
                  <span className="hidden font-mono text-[12px] md:block">
                    {r.resultVersionId ? (
                      <span className="text-[#8b95f6]">{r.resultVersionId}</span>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Badge kind={r.status} />
                    <ArrowRight
                      size={12}
                      className="hidden text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 md:block"
                    />
                  </span>
                </Link>
              </motion.div>
            )
          })}
        </AnimatePresence>

        {visible.length === 0 && (
          <div className="px-5 py-10 text-center text-[12.5px] text-ink-3">No runs match this filter.</div>
        )}
      </motion.div>
    </motion.div>
  )
}

const rise = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 320, damping: 30 } },
}
