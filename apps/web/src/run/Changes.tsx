import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CircleSlash, FilePen, Minus, Pencil, Plus } from 'lucide-react'
import type { ProposedChange, RunRecord, VersionNode } from '../data'
import { CountUp } from '../components/ui'
import { diffLines } from '../lib/diff'
import type { RunModel } from './model'
import { currentAttempt, seatStatus, laneGroups, stageState } from './derive'
import { Inline } from './Inline'
import { SeatChip } from './SeatChip'
import { DiffLine, Panel, RefChip, SessionChips, Skeleton } from './bits'
import { reveal, sameFocus } from './links'
import type { LinkApi } from './links'

const OP = { insert: Plus, update: Pencil, delete: Minus } as const

const trimBlank = (text: string | null | undefined) => {
  const lines = (text ?? '').split('\n')
  while (lines.length && !lines[0].trim()) lines.shift()
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  return lines
}

/**
 * Proposed changes and the combined diff, merged behind one toggle. While the
 * run is live the proposers' drafts slide in as they are submitted; verified
 * edits replace them once the commit lands.
 */
export function Changes({
  record,
  model,
  versions,
  edits,
  animate,
  links,
  onOpenAgent,
}: {
  record: RunRecord
  model: RunModel
  versions: VersionNode[]
  edits: ProposedChange[]
  animate: boolean
  links: LinkApi
  onOpenAgent: (key: string) => void
}) {
  const [mode, setMode] = useState<'edits' | 'diff'>('edits')
  const hasDiff = model.outcome === 'succeeded' && !!record.resultVersionId
  const view = hasDiff ? mode : 'edits'
  return (
    <Panel
      icon={<FilePen size={16} />}
      title="Proposed changes"
      count={edits.length ? <CountUp value={edits.length} /> : undefined}
      action={
        hasDiff && (
          <div className="flex rounded-md bg-ink/6 p-0.5 text-meta">
            {(['edits', 'diff'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded-[5px] px-2 py-0.5 ${view === m ? 'bg-panel text-ink shadow-sm' : 'text-ink-3 hover:text-ink-2'}`}
              >
                {m === 'edits' ? 'Edits' : 'Diff'}
              </button>
            ))}
          </div>
        )
      }
    >
      {view === 'diff' ? (
        <FileDiff base={versions.find((v) => v.id === record.baseVersionId)} result={versions.find((v) => v.id === record.resultVersionId)} />
      ) : edits.length ? (
        <ol className="pb-1">
          <AnimatePresence initial={false}>
            {edits.map((c, i) => (
              <motion.li
                key={i}
                id={`edit-${i}`}
                initial={animate ? { opacity: 0, x: 16 } : false}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: animate ? i * 0.06 : 0, ease: 'easeOut' }}
              >
                <EditItem i={i} change={c} links={links} muted={model.outcome !== 'succeeded'} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      ) : (
        <Drafts model={model} animate={animate} onOpenAgent={onOpenAgent} />
      )}
    </Panel>
  )
}

function EditItem({ i, change, links, muted }: { i: number; change: ProposedChange; links: LinkApi; muted: boolean }) {
  const { lit, pinned, pin, hover } = links
  const on = lit.edits.has(i)
  const findings = links.links.editFindings[i] ?? []
  const Op = OP[change.op]
  return (
    <article
      onMouseEnter={() => hover({ kind: 'edit', i })}
      onMouseLeave={() => hover(null)}
      className={`border-l-2 px-4 py-3 transition-[opacity,background-color] duration-150 ${on ? 'border-accent bg-accent/6' : 'border-transparent'} ${
        lit.any && !on ? 'opacity-50' : muted ? 'opacity-75' : ''
      }`}
    >
      <div className="flex items-center gap-2 text-body">
        <RefChip label={`E${i + 1}`} on={sameFocus(pinned, { kind: 'edit', i })} onClick={() => pin({ kind: 'edit', i })} title="Pin this edit" />
        <span
          className={`grid size-5 place-items-center rounded-[5px] ${change.op === 'delete' ? 'bg-red/12 text-red' : change.op === 'update' ? 'bg-amber/12 text-amber' : 'bg-green/12 text-green'}`}
          title={change.op}
        >
          <Op size={12} strokeWidth={2.5} />
        </span>
        <span className="truncate font-medium text-ink">{change.section}</span>
        {findings.length > 0 && (
          <span className="ml-auto flex shrink-0 items-center gap-1 text-meta text-ink-3">
            ←
            {findings.map((f) => (
              <RefChip
                key={f}
                label={`F${f + 1}`}
                on={sameFocus(pinned, { kind: 'finding', i: f })}
                onClick={() => {
                  pin({ kind: 'finding', i: f })
                  reveal(`finding-${f}`)
                }}
                title={`From finding ${f + 1}`}
              />
            ))}
          </span>
        )}
      </div>
      <div className="mt-2 overflow-hidden rounded-md border border-line py-1 font-mono text-meta leading-5">
        {trimBlank(change.before).map((l, k) => (
          <DiffLine key={`b${k}`} sign="−" text={l} />
        ))}
        {trimBlank(change.after).map((l, k) => (
          <DiffLine key={`a${k}`} sign="+" text={l} />
        ))}
      </div>
      <p className="mt-2 text-body text-ink-2">
        <Inline text={change.rationale} />
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        <SessionChips ids={change.evidence} lit={lit.sessions} />
      </div>
    </article>
  )
}

/** Before the verified edits exist: each proposer's draft as it arrives, with its edit count as blocks. */
function Drafts({ model, animate, onOpenAgent }: { model: RunModel; animate: boolean; onOpenAgent: (key: string) => void }) {
  const attempt = currentAttempt(model).n
  const drafts = model.drafts.filter((d) => d.attempt === attempt)
  const propose = stageState(model, 'propose')
  const proposers = laneGroups(model)[1].panel
  if (!drafts.length) {
    if (propose === 'active' || propose === 'retry') {
      return (
        <div className="flex flex-col gap-1 py-2">
          {proposers.map((s) => (
            <div key={s.key} className="flex items-center gap-3 px-4 py-1.5">
              <SeatChip seat={s} />
              <span className={`h-2.5 w-32 rounded ${seatStatus(model, s) === 'running' ? 'shimmer' : 'bg-panel-2'}`} />
            </div>
          ))}
        </div>
      )
    }
    if (model.outcome === 'failed' || model.outcome === 'no-changes') {
      return (
        <div className="flex items-center gap-2 px-4 py-4 text-body text-ink-3">
          <CircleSlash size={15} /> Nothing applied
        </div>
      )
    }
    return null
  }
  return (
    <ol className="py-1">
      {drafts.map((d) => {
        const seat = model.seats.find((s) => s.key === d.agent)
        return (
          <motion.li
            key={`${d.agent}-${d.at}`}
            initial={animate ? { opacity: 0, x: 16 } : false}
            animate={{ opacity: model.outcome === 'running' ? 1 : 0.7, x: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
          >
            <button onClick={() => onOpenAgent(d.agent)} className="hover-row flex w-full items-start gap-3 px-4 py-2.5 text-left">
              {seat && <SeatChip seat={seat} />}
              <span className="flex shrink-0 gap-[3px] pt-1.5" aria-label={`${d.edits.length} drafted edits`}>
                {d.edits.map((_, k) => (
                  <span key={k} className="size-2 rounded-[2px] bg-green/70" />
                ))}
              </span>
              {d.note && <span className="line-clamp-2 text-body text-ink-2">{d.note}</span>}
            </button>
          </motion.li>
        )
      })}
    </ol>
  )
}

function FileDiff({ base, result }: { base?: VersionNode; result?: VersionNode }) {
  const rows = useMemo(() => (base && result ? diffLines(base.file, result.file) : []), [base, result])
  if (!rows.length) return <Skeleton />
  const near = (i: number) => rows.slice(Math.max(0, i - 2), i + 3).some((r) => r.type !== 'ctx')
  return (
    <div className="m-3 overflow-hidden rounded-md border border-line py-1 font-mono text-meta leading-5">
      {rows.map((r, i) =>
        near(i) ? (
          <DiffLine key={i} sign={r.type === 'add' ? '+' : r.type === 'del' ? '−' : ' '} text={r.text} a={r.a} b={r.b} />
        ) : near(i - 1) ? (
          <div key={i} className="px-3 text-center text-ink-3 select-none">
            ⋯
          </div>
        ) : null,
      )}
    </div>
  )
}
