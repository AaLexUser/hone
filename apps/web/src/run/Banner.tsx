import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowRight, CircleDashed, CircleX, GitCommitHorizontal, RotateCw } from 'lucide-react'
import type { RunRecord, VersionNode } from '../data'
import { diffLines } from '../lib/diff'
import type { RunModel } from './model'
import { attemptStories, fmtDuration, shortModel } from './derive'
import type { AttemptStory, NowLine } from './derive'
import { SeatChip } from './SeatChip'

/**
 * The paper's commit banner, one per outcome: the commit with its diffstat,
 * the failed attempts with their seat and cause, the no-changes note, or
 * while live the single "now" line.
 */
export function Banner({
  record,
  model,
  versions,
  now,
  elapsed,
}: {
  record: RunRecord
  model: RunModel
  versions: VersionNode[]
  now: NowLine | null
  elapsed: number
}) {
  if (now) return <LiveBanner now={now} elapsed={elapsed} />
  if (model.outcome === 'succeeded' || (model.outcome === 'running' && record.status === 'succeeded')) {
    return <CommitBanner record={record} model={model} versions={versions} />
  }
  if (model.outcome === 'failed') return <FailedBanner record={record} stories={attemptStories(model)} />
  if (model.outcome === 'no-changes') return <QuietBanner record={record} />
  return null
}

const SHELL = 'mb-4 rounded-[10px] border px-5 py-4'

const STAGE_TONE = {
  review: 'text-rev bg-rev/12',
  propose: 'text-pro bg-pro/12',
  verify: 'text-accent-2 bg-accent/12',
  setup: 'text-ink-2 bg-ink/6',
} as const

function LiveBanner({ now, elapsed }: { now: NowLine; elapsed: number }) {
  return (
    <div className={`${SHELL} flex h-14 items-center gap-3 border-accent/30 bg-accent/[0.05] py-0`} aria-live="polite">
      <span className="pulse-dot size-2 rounded-full bg-accent" />
      <span className={`rounded-[5px] px-1.5 py-px text-[12px] font-semibold ${STAGE_TONE[now.stage]}`}>
        {now.stage === 'setup' ? 'Batch' : now.stage.charAt(0).toUpperCase() + now.stage.slice(1)}
      </span>
      {/* A fresh span per line that only ever fades in, so a quick change of line can never strand one half-faded. */}
      <motion.span
        key={now.text}
        initial={{ opacity: 0.3, y: 3 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className="truncate text-emph font-medium text-ink"
      >
        {now.text}
      </motion.span>
      <span className="ml-auto font-mono text-emph text-ink-2 tabular-nums">{fmtDuration(elapsed)}</span>
    </div>
  )
}

function DiffStat({ record, versions }: { record: RunRecord; versions: VersionNode[] }) {
  const stat = useMemo(() => {
    const a = versions.find((v) => v.id === record.baseVersionId)
    const b = versions.find((v) => v.id === record.resultVersionId)
    if (!a || !b) return null
    const rows = diffLines(a.file, b.file)
    return { add: rows.filter((r) => r.type === 'add').length, del: rows.filter((r) => r.type === 'del').length }
  }, [record, versions])
  if (!stat) return null
  const total = Math.max(1, stat.add + stat.del)
  const greens = Math.round((stat.add / total) * 5)
  return (
    <span className="flex items-center gap-2 font-mono text-meta tabular-nums" title={`${stat.add} lines added, ${stat.del} removed`}>
      <span className="text-green">+{stat.add}</span>
      <span className="text-red">−{stat.del}</span>
      <span className="flex gap-[2px]">
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={`size-2 rounded-[2px] ${i < greens ? 'bg-green' : stat.del ? 'bg-red' : 'bg-line-2'}`} />
        ))}
      </span>
    </span>
  )
}

function CommitBanner({ record, model, versions }: { record: RunRecord; model: RunModel; versions: VersionNode[] }) {
  const retries = model.attempts.length - 1
  return (
    <div className={`${SHELL} border-green/30 bg-green/[0.06]`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <GitCommitHorizontal size={18} className="text-green" />
        <span className="text-emph text-ink">
          Committed <span className="font-mono font-semibold text-green">{record.resultVersionId}</span>
          {record.commitBranch && (
            <>
              {' '}
              on <span className="font-mono">{record.commitBranch}</span>
            </>
          )}
        </span>
        <span className="flex items-center gap-1.5 font-mono text-meta text-ink-3">
          {record.baseVersionId} <ArrowRight size={12} /> {record.resultVersionId}
        </span>
        <DiffStat record={record} versions={versions} />
        {retries > 0 && (
          <span className="flex items-center gap-1 rounded-[5px] bg-amber/12 px-1.5 py-px text-meta font-medium text-amber" title={`Passed on attempt ${retries + 1}`}>
            <RotateCw size={12} /> {retries + 1}
          </span>
        )}
        <span className="ml-auto flex gap-2">
          <Link to="/versions" className="btn-primary flex items-center gap-1.5 rounded-md px-3 py-1.5 text-body font-medium">
            View version <ArrowRight size={14} />
          </Link>
          <Link to="/runs" className="btn-ghost rounded-md px-3 py-1.5 text-body text-ink-2">
            All runs
          </Link>
        </span>
      </div>
      {record.commitTitle && <div className="mt-3 font-mono text-[14px] font-medium text-ink">{record.commitTitle}</div>}
      {record.commitBody && <p className="mt-1.5 max-w-[110ch] text-body text-ink-2">{record.commitBody}</p>}
    </div>
  )
}

/** Consecutive attempts that failed the same way read as one line. */
function groupStories(stories: AttemptStory[]) {
  const groups: { from: number; to: number; story: AttemptStory }[] = []
  for (const s of stories.filter((x) => x.state === 'crashed' || x.state === 'rejected')) {
    const last = groups[groups.length - 1]
    if (last && last.to === s.n - 1 && last.story.seat?.key === s.seat?.key && last.story.plain === s.plain) last.to = s.n
    else groups.push({ from: s.n, to: s.n, story: s })
  }
  return groups
}

const Dot = () => <span className="text-ink-3">·</span>

function FailedBanner({ record, stories }: { record: RunRecord; stories: AttemptStory[] }) {
  return (
    <div className={`${SHELL} border-red/30 bg-red/[0.05]`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <CircleX size={18} className="text-red" />
        <span className="text-emph font-medium text-ink">No new version</span>
        <span className="text-body text-ink-3">
          AGENTS.md stays at <span className="font-mono text-ink-2">{record.baseVersionId}</span>
        </span>
        <Link to="/runs" className="btn-ghost ml-auto rounded-md px-3 py-1.5 text-body text-ink-2">
          All runs
        </Link>
      </div>
      <ul className="mt-2.5 flex flex-col gap-1.5 pl-[30px]">
        {groupStories(stories).map(({ from, to, story }) => (
          <li key={from} className="flex flex-wrap items-center gap-x-2 text-body" title={story.detail}>
            <span className="font-medium text-ink tabular-nums">{from === to ? `Attempt ${from}` : `Attempts ${from}–${to}`}</span>
            <Dot />
            {story.seat ? (
              <>
                <SeatChip seat={story.seat} />
                <span className="font-mono text-meta text-ink-3">{shortModel(story.seat.model)}</span>
              </>
            ) : (
              <span className="text-ink-2">{story.cause}</span>
            )}
            <Dot />
            <span className="text-red">{story.plain || story.cause || 'did not finish'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function QuietBanner({ record }: { record: RunRecord }) {
  return (
    <div className={`${SHELL} border-line-2 bg-panel`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <CircleDashed size={18} className="text-ink-3" />
        <span className="text-emph font-medium text-ink">No changes</span>
        <span className="text-body text-ink-3">
          AGENTS.md stays at <span className="font-mono text-ink-2">{record.baseVersionId}</span>
        </span>
        <Link to="/runs" className="btn-ghost ml-auto rounded-md px-3 py-1.5 text-body text-ink-2">
          All runs
        </Link>
      </div>
      {record.note && <p className="mt-2 text-body text-ink-2">{record.note.replace(/\.{2,}/g, '.')}</p>}
    </div>
  )
}
