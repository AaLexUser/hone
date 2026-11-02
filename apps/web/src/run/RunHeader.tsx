import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import type { RunOutcome, RunRecord } from '../data'
import { relTime } from '../store'
import { fmtDuration } from './derive'

/** Breadcrumb, "Optimization run" with its status badge, and the paper's four facts on the right in short words. */
export function RunHeader({ record, outcome, elapsed, attempts }: { record: RunRecord; outcome: RunOutcome; elapsed: number; attempts: number }) {
  return (
    <header className="mb-4">
      <nav className="mb-3 flex items-center gap-1 text-body text-ink-3">
        <Link to="/runs" className="hover:text-ink-2">
          Runs
        </Link>
        <ChevronRight size={14} />
        <span className="font-mono text-meta text-ink-2">run {record.id}</span>
      </nav>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <h1 className="flex items-center gap-3 text-[22px] leading-8 font-semibold tracking-tight text-ink">
          Optimization run
          <StatusPill outcome={outcome} />
        </h1>
        <dl className="ml-auto flex items-baseline gap-2 text-body text-ink-3 tabular-nums">
          <Fact label="started">{relTime(record.startedAt)}</Fact>
          <Sep />
          <Fact label="batch">{record.traceIds.length}</Fact>
          <Sep />
          <Fact label="attempt" tone={attempts > 1 ? 'text-amber' : undefined}>
            {attempts}
          </Fact>
          <Sep />
          <Fact label="elapsed" hidden>
            {fmtDuration(elapsed)}
          </Fact>
        </dl>
      </div>
    </header>
  )
}

const PILL: Record<RunOutcome, string> = {
  running: 'text-accent-2 bg-accent/10 ring-accent/30',
  validating: 'text-accent-2 bg-accent/10 ring-accent/30',
  succeeded: 'text-green bg-green/10 ring-green/30',
  failed: 'text-red bg-red/10 ring-red/30',
  'no-changes': 'text-ink-2 bg-ink/5 ring-line-2',
}

function StatusPill({ outcome }: { outcome: RunOutcome }) {
  const live = outcome === 'running' || outcome === 'validating'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-meta font-medium ring-1 ring-inset ${PILL[outcome]}`}>
      {live && <span className="pulse-dot size-1.5 rounded-full bg-current" />}
      {outcome === 'no-changes' ? 'no changes' : outcome}
    </span>
  )
}

const Sep = () => <span aria-hidden>·</span>

/** A short word and its value: "started 11d ago", "batch 4"; elapsed shows only its value. */
function Fact({ label, hidden, tone, children }: { label: string; hidden?: boolean; tone?: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className={hidden ? 'sr-only' : undefined}>{label}</dt>
      <dd className={`font-medium ${tone ?? 'text-ink-2'}`}>{children}</dd>
    </div>
  )
}
