import { useCallback, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import type { ReviewItem } from '../data'
import { useStore } from '../store'
import { useRun, useRunClock } from '../run/useRun'
import { isTerminal } from '../run/model'
import type { RunModel } from '../run/model'
import { laneGroups, nowLine, seatStatus, stageState } from '../run/derive'
import type { StageState } from '../run/derive'
import type { Stage } from '../run/events'
import { RunHeader } from '../run/RunHeader'
import { Banner } from '../run/Banner'
import { PipelineGraph } from '../run/graph/PipelineGraph'
import { Activity } from '../run/Activity'
import { Batch } from '../run/Batch'
import { Findings } from '../run/Findings'
import { Changes } from '../run/Changes'
import { Drawer } from '../run/Drawer'
import type { DrawerTarget } from '../run/Drawer'
import { useLinks } from '../run/links'

const NO_FINDINGS: ReviewItem[] = []

/** One optimization run, laid out as in the paper: header, commit banner, MAJICS pipeline, then activity beside the report and changes. */
export function RunPage() {
  const { id = '' } = useParams()
  const { state } = useStore()
  const { record, model, review, arrivedAt, caughtUp } = useRun(id)
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null)
  const [filter, setFilter] = useState<string | null>(null)

  const outcome = isTerminal(model.outcome) ? model.outcome : (record?.status ?? 'running')
  const live = !!record && !isTerminal(outcome)
  const now = useRunClock(model.lastAt, arrivedAt, live)
  const animate = live && caughtUp
  const edits = useMemo(() => {
    const all = record?.changes ?? []
    return live ? all.slice(0, model.revealed) : all
  }, [record, live, model.revealed])
  const links = useLinks(review?.findings ?? NO_FINDINGS, edits)

  const openAgent = useCallback((key: string) => setDrawer({ type: 'agent', key }), [])
  const closeDrawer = useCallback(() => setDrawer(null), [])

  if (record === undefined) return <div className="py-16 text-center text-body text-ink-3">Loading run…</div>
  if (record === null) return <div className="py-16 text-center text-body text-ink-3">Run not found.</div>

  const elapsed = live ? now : record.durationMs || model.lastAt
  const sessions = record.traceIds.map((t) => ({ id: t, feedback: !!state.traces.find((x) => x.id === t)?.feedback }))

  return (
    <MotionConfig reducedMotion="user">
      <div className="tv-scale">
        <RunHeader record={record} outcome={outcome} elapsed={elapsed} attempts={Math.max(record.attempts, model.attempts.length)} />
        <Banner record={record} model={model} versions={state.versions} now={live ? nowLine(model, sessions.length) : null} elapsed={elapsed} />

        <section className="card mb-4 overflow-hidden">
          <header className="flex h-12 items-center gap-2 border-b border-line px-5">
            <h2 className="text-emph font-semibold text-ink">MAJICS pipeline</h2>
            <span className="ml-auto flex gap-2">
              <StageChip stage="review" model={model} />
              <StageChip stage="propose" model={model} />
            </span>
          </header>
          <div className="px-4 py-4">
            <PipelineGraph
              model={model}
              sessions={sessions}
              findings={review ? review.findings.length : null}
              commitId={outcome === 'succeeded' ? record.resultVersionId : null}
              selected={filter}
              onSelect={(key) => setFilter((f) => (f === key ? null : key))}
              animate={animate}
            />
          </div>
        </section>

        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.12fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <Activity
              model={model}
              now={now}
              live={live}
              animate={animate}
              filter={filter}
              onFilter={setFilter}
              onOpenAgent={openAgent}
              onOpenEvents={() => setDrawer((d) => (d?.type === 'events' ? null : { type: 'events' }))}
            />
            <Batch ids={record.traceIds} traces={state.traces} base={record.baseVersionId} links={links} />
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <Findings runId={record.id} review={review} writing={reviewJudgeWriting(model)} links={links} />
            <Changes
              record={record}
              model={model}
              versions={state.versions}
              edits={edits}
              animate={animate}
              links={links}
              onOpenAgent={openAgent}
            />
          </div>
        </div>

        {drawer && <Drawer target={drawer} model={model} onClose={closeDrawer} />}
      </div>
    </MotionConfig>
  )
}

function reviewJudgeWriting(m: RunModel): boolean {
  const judge = laneGroups(m)[0].judge
  return stageState(m, 'review') === 'active' && !!judge && seatStatus(m, judge) === 'running'
}

const CHIP: Record<StageState, { word: string; cls: string }> = {
  pending: { word: 'waiting', cls: 'text-ink-3 ring-line-2' },
  skipped: { word: 'skipped', cls: 'text-ink-3 ring-line-2' },
  active: { word: 'live', cls: 'text-accent-2 bg-accent/10 ring-accent/35' },
  done: { word: 'done', cls: 'text-green bg-green/8 ring-green/30' },
  retry: { word: 'retry', cls: 'text-amber bg-amber/10 ring-amber/35' },
  failed: { word: 'failed', cls: 'text-red bg-red/8 ring-red/30' },
}

/** The paper's "review · done" chips, one per stage. */
function StageChip({ stage, model }: { stage: Stage; model: RunModel }) {
  const s = stageState(model, stage)
  const { word, cls } = CHIP[s]
  return (
    <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-meta ring-1 ring-inset ${cls}`}>
      <span className={`size-1.5 rounded-full bg-current ${s === 'active' ? 'pulse-dot' : ''}`} />
      {stage} · {word}
    </span>
  )
}
