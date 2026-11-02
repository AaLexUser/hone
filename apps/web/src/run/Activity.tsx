import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Check, ChevronRight, CircleAlert, Clock3, FileText, GitCommitHorizontal, Layers, ListTree, PanelRightOpen, RotateCw, Wrench, X } from 'lucide-react'
import type { RunModel } from './model'
import { activityRows, gist, toolGist } from './activity'
import type { AskRow, Row, WorkRow } from './activity'
import { laneGroups, groupSeats, monogram, plainError } from './derive'
import { SeatChip } from './SeatChip'
import { Inline } from './Inline'

/**
 * The paper's Activity region, compressed: agents are monogram chips, each
 * stretch of work is one row with its tool calls folded inside, and the
 * judge's follow-ups nest the answers they got. Raw events open in the drawer.
 */
export function Activity({
  model,
  now,
  live,
  animate,
  filter,
  onFilter,
  onOpenAgent,
  onOpenEvents,
}: {
  model: RunModel
  now: number
  live: boolean
  animate: boolean
  filter: string | null
  onFilter: (key: string | null) => void
  onOpenAgent: (key: string) => void
  onOpenEvents: () => void
}) {
  const rows = useMemo(() => activityRows(model), [model])
  const shown = filter ? rows.filter((r) => involves(r, filter)) : rows
  const scroller = useRef<HTMLOListElement>(null)
  const pinned = useRef(true)

  const [edges, setEdges] = useState({ above: false, below: false })
  const measure = (el: HTMLElement) =>
    setEdges({ above: el.scrollTop > 4, below: el.scrollHeight - el.scrollTop - el.clientHeight > 4 })

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    if (live && pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: animate ? 'smooth' : 'auto' })
    measure(el)
  }, [shown.length, live, animate, model.events.length])

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3">
        <h2 className="text-emph font-semibold text-ink">Activity</h2>
        <div className="flex flex-wrap items-center gap-1">
          <FilterButton on={filter === null} onClick={() => onFilter(null)}>
            all
          </FilterButton>
          {laneGroups(model).map((g) => (
            <span key={g.stage} className="flex items-center gap-1 pl-1.5">
              {groupSeats(g).map((s) => (
                <button
                  key={s.key}
                  onClick={() => onFilter(filter === s.key ? null : s.key)}
                  className={`rounded-md p-0.5 ${filter === s.key ? 'bg-ink/10' : 'hover:bg-panel-2'}`}
                  aria-pressed={filter === s.key}
                >
                  <SeatChip seat={s} dim={filter !== null && filter !== s.key} />
                </button>
              ))}
            </span>
          ))}
        </div>
        <button
          onClick={onOpenEvents}
          title="Raw event stream"
          className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-meta text-ink-3 tabular-nums hover:bg-panel-2 hover:text-ink-2"
        >
          <ListTree size={14} />
          {model.events.length}
        </button>
      </header>
      <ol
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
          measure(el)
        }}
        className={`py-1.5 ${live ? 'max-h-[560px] overflow-y-auto' : ''}`}
        style={{ maskImage: fade(live && edges.above, live && edges.below) }}
      >
        {shown.map((r) => (
          <motion.li
            key={r.id}
            initial={animate ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
          >
            <RowView row={r} now={now} onOpenAgent={onOpenAgent} />
          </motion.li>
        ))}
        {!shown.length && <li className="px-4 py-6 text-body text-ink-3">Nothing yet.</li>}
      </ol>
    </section>
  )
}

/** Soft edges where the live feed scrolls on, so a cut-off row reads as "more", not as clipped. */
function fade(above: boolean, below: boolean): string | undefined {
  if (!above && !below) return undefined
  return `linear-gradient(to bottom, ${above ? 'transparent, black 40px' : 'black'}, ${below ? 'black calc(100% - 40px), transparent' : 'black'})`
}

function involves(r: Row, key: string): boolean {
  if (r.type === 'work') return r.seat.key === key
  if (r.type === 'ask') return r.judge.key === key || r.answers.some((a) => a.seat.key === key)
  if (r.type === 'failed') return r.story.seat?.key === key
  return false
}

function FilterButton({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-2 py-0.5 text-meta font-medium ${on ? 'bg-accent/12 text-accent-2' : 'text-ink-3 hover:bg-panel-2'}`}
    >
      {children}
    </button>
  )
}

function RowView({ row, now, onOpenAgent }: { row: Row; now: number; onOpenAgent: (key: string) => void }) {
  switch (row.type) {
    case 'stage':
      return (
        <div className="flex items-center gap-2 px-4 pt-3 pb-1">
          <span className={`text-[12px] font-semibold tracking-[0.12em] ${row.stage === 'review' ? 'text-rev' : 'text-pro'}`}>
            {row.stage.toUpperCase()}
          </span>
          {row.attempt > 1 && (
            <span className="flex items-center gap-1 rounded-[4px] bg-amber/12 px-1.5 text-meta text-amber">
              <RotateCw size={11} /> {row.attempt}
            </span>
          )}
          <span className="h-px flex-1 bg-line" />
        </div>
      )
    case 'batch':
      return (
        <Milestone icon={<Layers size={14} className="text-ink-3" />}>
          Batch frozen<span className="ml-1.5 text-ink-3 tabular-nums">· {row.sessions}</span>
        </Milestone>
      )
    case 'report':
      return <Milestone icon={<FileText size={14} className="text-amber" />}>Report ready</Milestone>
    case 'commit':
      return (
        <Milestone icon={<GitCommitHorizontal size={14} className="text-green" />}>
          <span className="truncate font-mono text-meta text-ink">{row.title}</span>
        </Milestone>
      )
    case 'failed':
      return (
        <Milestone icon={<CircleAlert size={14} className="text-red" />}>
          <span className="text-red">Attempt {row.story.n}</span>
          {row.story.seat && (
            <span className="ml-1.5">
              <SeatChip seat={row.story.seat} />
            </span>
          )}
          <span className="ml-1.5 text-ink-2">{row.story.plain || row.story.cause}</span>
        </Milestone>
      )
    case 'ask':
      return <AskView row={row} now={now} onOpenAgent={onOpenAgent} />
    case 'work':
      return <WorkView row={row} now={now} onOpenAgent={onOpenAgent} />
  }
}

function Milestone({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex h-8 items-center gap-2.5 px-4 text-body text-ink-2">
      <span className="grid w-7 place-items-center">{icon}</span>
      <span className="flex min-w-0 items-center">{children}</span>
    </div>
  )
}

function StatusIcon({ row }: { row: WorkRow }) {
  if (row.span.end === null) return <Spinner />
  if (row.span.error)
    return row.span.followUp ? (
      <Clock3 size={14} className="text-amber" aria-label="timed out" />
    ) : (
      <X size={14} className="text-red" aria-label="failed" />
    )
  return <Check size={14} className="text-green" aria-label="done" />
}

function Spinner() {
  return (
    <svg width={14} height={14} viewBox="-8 -8 16 16" aria-label="working">
      <circle r={6} fill="none" strokeWidth={1.6} className="stroke-accent/25" />
      <circle r={6} fill="none" strokeWidth={1.6} pathLength={100} strokeDasharray="28 72" strokeLinecap="round" className="spin-arc stroke-accent" />
    </svg>
  )
}

/** Where this stretch of work sat inside its stage, as a thin bar instead of timestamps. */
function TimeBar({ row, now }: { row: WorkRow; now: number }) {
  const [w0, w1raw] = row.window
  const w1 = Math.max(w1raw ?? now, row.span.end ?? now, w0 + 1)
  const a = (row.span.start - w0) / (w1 - w0)
  const b = ((row.span.end ?? now) - w0) / (w1 - w0)
  const tone = row.span.end === null ? 'bg-accent' : row.span.error ? (row.span.followUp ? 'bg-amber' : 'bg-red') : 'bg-ink-3/55'
  return (
    <span className="relative h-1.5 w-16 shrink-0 rounded-full bg-line" aria-hidden>
      <span
        className={`absolute inset-y-0 rounded-full ${tone} transition-[left,width] duration-300`}
        style={{ left: `${Math.max(0, a) * 100}%`, width: `${Math.max(0.04, Math.min(1, b) - Math.max(0, a)) * 100}%` }}
      />
    </span>
  )
}

function WorkView({ row, now, onOpenAgent, nested = false }: { row: WorkRow; now: number; onOpenAgent: (key: string) => void; nested?: boolean }) {
  const [open, setOpen] = useState(false)
  const text = row.text ? gist(row.text) : null
  const last = row.tools.at(-1)
  return (
    <div className={nested ? 'pl-9' : ''}>
      <button
        onClick={() => setOpen(!open)}
        className="hover-row grid h-9 w-full grid-cols-[auto_auto_minmax(0,1fr)_auto_auto_auto] items-center gap-2.5 px-4 text-left"
        aria-expanded={open}
      >
        <SeatChip seat={row.seat} />
        <StatusIcon row={row} />
        {text ? (
          <span className="truncate text-body text-ink">
            <Inline text={text} />
          </span>
        ) : row.span.error ? (
          <span className="truncate text-body text-red">{plainError(row.span.error)}</span>
        ) : (
          <span className="truncate text-body text-ink-3">{last ? toolGist(last) : ''}</span>
        )}
        <span className="flex items-center gap-2 text-meta text-ink-3 tabular-nums">
          {row.retries > 0 && (
            <span className="flex items-center gap-0.5 text-amber" title={`${row.retries} transport retry`}>
              <RotateCw size={12} />
              {row.retries}
            </span>
          )}
          {row.drafted !== null && (
            <span className="rounded-[4px] bg-green/12 px-1 font-medium text-green" title={`${row.drafted} drafted edits`}>
              +{row.drafted}
            </span>
          )}
          {row.tools.length > 0 && (
            <span className="flex items-center gap-1" title={`${row.tools.length} tool calls`}>
              <Wrench size={12} />
              {row.tools.length}
            </span>
          )}
        </span>
        <TimeBar row={row} now={now} />
        <ChevronRight size={14} className={`text-ink-3 transition-transform duration-150 ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="mx-4 mb-2 ml-[52px] flex flex-col gap-2 border-l border-line pl-3">
          {row.text && <p className="text-body whitespace-pre-wrap text-ink-2">{row.text.replace(/^#+\s*/gm, '')}</p>}
          {row.span.error && <p className="font-mono text-meta break-words text-red">{row.span.error}</p>}
          {row.tools.length > 0 && (
            <ol className="flex flex-col gap-0.5 text-body text-ink-2">
              {runs(row.tools.map(toolGist)).map(([gist, n], i) => (
                <li key={i} className="flex items-center gap-2">
                  <Wrench size={12} className="shrink-0 text-ink-3" />
                  <span className="truncate">{gist}</span>
                  {n > 1 && <span className="text-meta text-ink-3 tabular-nums">×{n}</span>}
                </li>
              ))}
            </ol>
          )}
          <button
            onClick={() => onOpenAgent(row.seat.key)}
            className="flex w-fit items-center gap-1.5 rounded-md px-1.5 py-0.5 text-meta text-ink-3 hover:bg-panel-2 hover:text-ink"
          >
            <PanelRightOpen size={13} /> Trajectory
          </button>
        </div>
      )}
    </div>
  )
}

/** Consecutive repeats folded into one entry with a count. */
function runs(items: string[]): [string, number][] {
  const out: [string, number][] = []
  for (const x of items) {
    const last = out[out.length - 1]
    if (last && last[0] === x) last[1]++
    else out.push([x, 1])
  }
  return out
}

function AskView({ row, now, onOpenAgent }: { row: AskRow; now: number; onOpenAgent: (key: string) => void }) {
  const live = row.end === null
  return (
    <div className={`my-1 ${live ? 'bg-accent/5' : ''}`}>
      <div className="flex h-9 items-center gap-2.5 px-4 text-body">
        <SeatChip seat={row.judge} />
        <span
          className={`grid size-[18px] place-items-center rounded-full text-[12px] font-bold text-white ${live ? 'pulse-dot bg-accent' : 'bg-accent/80'}`}
          aria-label="asked the panel"
        >
          ?
        </span>
        <span className="flex items-center gap-1">
          {row.answers.map((a) => (
            <span key={a.id} className={row.timedOut.includes(a.seat.key) ? 'opacity-60' : ''}>
              <SeatChip seat={a.seat} />
            </span>
          ))}
        </span>
        {row.timedOut.length > 0 && (
          <span className="flex items-center gap-1 text-meta text-amber">
            <Clock3 size={12} /> {row.timedOut.length}
          </span>
        )}
        <span className="sr-only">
          judge asked {row.answers.map((a) => monogram(a.seat)).join(', ')}
        </span>
      </div>
      {row.answers.map((a) => (
        <WorkView key={a.id} row={a} now={now} onOpenAgent={onOpenAgent} nested />
      ))}
    </div>
  )
}
