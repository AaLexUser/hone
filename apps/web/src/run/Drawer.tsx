import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, X } from 'lucide-react'
import type { DraftEdit, RunEvent, RunEventKind } from './events'
import type { RunModel } from './model'
import { busyMs, fmtDuration, laneStatus, seatLabel, stageName } from './derive'
import { StatusDot } from './StatusDot'

export type DrawerTarget = { type: 'agent'; key: string } | { type: 'events' }

/** One docked drawer for all debug detail: an agent's trajectory, or the raw event stream. */
export function Drawer({ target, model, onClose }: { target: DrawerTarget; model: RunModel; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
      <div className="scrim-in fixed inset-x-0 top-12 bottom-0 z-20 bg-[oklch(0.2_0.01_270/0.22)]" onClick={onClose} aria-hidden />
      <aside
        className="drawer-in fixed top-12 right-0 bottom-0 z-30 flex w-[560px] max-w-full flex-col border-l border-line bg-panel shadow-[0_8px_40px_-8px_oklch(0_0_0/0.45)]"
        aria-label="Run detail"
      >
        {target.type === 'agent' ? (
          <AgentTrajectory agent={target.key} model={model} onClose={onClose} />
        ) : (
          <RawEvents model={model} onClose={onClose} />
        )}
      </aside>
    </>
  )
}

function DrawerHead({ title, sub, onClose, children }: { title: string; sub: string; onClose: () => void; children?: React.ReactNode }) {
  return (
    <div className="border-b border-line px-5 pt-4 pb-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-section font-semibold text-ink">{title}</h2>
          <div className="mt-0.5 truncate font-mono text-meta text-ink-3">{sub}</div>
        </div>
        <button onClick={onClose} className="ml-auto grid size-7 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-panel-2 hover:text-ink" aria-label="Close">
          <X size={16} />
        </button>
      </div>
      {children}
    </div>
  )
}

const clock = (at: number) => `${Math.floor(at / 60000)}:${String(Math.floor((at % 60000) / 1000)).padStart(2, '0')}`

/* ---------------------------------------------------------- trajectory */

type Item =
  | { type: 'start'; at: number; followUp: boolean; attempt: number }
  | { type: 'tools'; at: number; calls: { at: number; name: string; detail?: string }[] }
  | { type: 'message'; at: number; text: string }
  | { type: 'retry'; at: number; reason: string }
  | { type: 'end'; at: number; ok: boolean; durationMs?: number; error?: string }
  | { type: 'proposal'; at: number; note?: string; edits: DraftEdit[] }
  | { type: 'ask'; at: number; asked: number; timedOut: string[] }

function trajectory(model: RunModel, agent: string): Item[] {
  const spans = model.lanes[agent]?.spans ?? []
  const items: Item[] = []
  for (const ev of model.events) {
    if (!('agent' in ev) || ev.agent !== agent) continue
    const last = items[items.length - 1]
    switch (ev.kind) {
      case 'agent_start': {
        const span = spans.find((s) => s.start === ev.at)
        items.push({ type: 'start', at: ev.at, followUp: !!span?.followUp, attempt: span?.attempt ?? 1 })
        break
      }
      case 'tool':
        if (last?.type === 'tools') last.calls.push({ at: ev.at, name: ev.name, detail: ev.detail })
        else items.push({ type: 'tools', at: ev.at, calls: [{ at: ev.at, name: ev.name, detail: ev.detail }] })
        break
      case 'message':
        items.push({ type: 'message', at: ev.at, text: ev.text })
        break
      case 'retry':
        items.push({ type: 'retry', at: ev.at, reason: ev.reason })
        break
      case 'agent_end':
        items.push({ type: 'end', at: ev.at, ok: ev.ok, durationMs: ev.durationMs, error: ev.error })
        break
      case 'proposal':
        items.push({ type: 'proposal', at: ev.at, note: ev.note, edits: ev.edits })
        break
      case 'ask_panel':
        items.push({ type: 'ask', at: ev.at, asked: ev.asked, timedOut: ev.timedOut })
        break
    }
  }
  return items
}

function AgentTrajectory({ agent, model, onClose }: { agent: string; model: RunModel; onClose: () => void }) {
  const seat = model.seats.find((s) => s.key === agent)
  const lane = model.lanes[agent]
  const items = useMemo(() => trajectory(model, agent), [model, agent])
  const status = laneStatus(lane)
  const tools = lane?.tools.length ?? 0
  const followUps = lane?.spans.filter((s) => s.followUp).length ?? 0
  return (
    <>
      <DrawerHead title={seat ? (seat.judge ? seatLabel(seat) : `${stageName(seat.stage)} · ${seatLabel(seat)}`) : agent} sub={seat?.model ?? ''} onClose={onClose}>
        <div className="mt-3 flex items-center gap-4 text-meta text-ink-3">
          <span className="flex items-center gap-1.5 text-ink-2">
            <StatusDot tone={status === 'running' ? 'live' : status === 'error' ? 'failed' : status === 'done' ? 'done' : 'idle'} className="size-1.5" />
            {status === 'idle' ? 'waiting' : status}
          </span>
          <span className="tabular-nums">{fmtDuration(busyMs(lane, model.lastAt))} busy</span>
          <span>{tools} tool calls</span>
          {followUps > 0 && <span>{followUps === 1 ? '1 follow-up' : `${followUps} follow-ups`}</span>}
        </div>
      </DrawerHead>
      <ol className="flex-1 overflow-y-auto px-5 py-3">
        {items.length === 0 && <li className="py-6 text-body text-ink-3">Nothing yet. This agent starts when its stage does.</li>}
        {items.map((it, i) => (
          <li key={i} className="relative flex gap-3 py-1.5">
            <span className="w-10 shrink-0 pt-0.5 text-right font-mono text-meta text-ink-3 tabular-nums">{clock(it.at)}</span>
            <div className="min-w-0 flex-1">
              <TrajectoryItem item={it} />
            </div>
          </li>
        ))}
      </ol>
    </>
  )
}

function TrajectoryItem({ item }: { item: Item }) {
  switch (item.type) {
    case 'start':
      return (
        <div className="text-body font-medium text-ink">
          {item.followUp ? 'Answering a follow-up from the judge' : item.attempt > 1 ? `Started attempt ${item.attempt}` : 'Started'}
        </div>
      )
    case 'tools':
      return <ToolGroup calls={item.calls} />
    case 'message':
      return (
        <div className="rounded-md bg-panel-2 px-3 py-2 text-body whitespace-pre-wrap text-ink">
          {item.text.split('\n').map((line, i) =>
            line.startsWith('#') ? (
              <div key={i} className="font-semibold">
                {line.replace(/^#+\s*/, '')}
              </div>
            ) : (
              <div key={i}>{line || ' '}</div>
            ),
          )}
        </div>
      )
    case 'retry':
      return <div className="text-body text-amber">Retried: {item.reason}</div>
    case 'end':
      return item.ok ? (
        <div className="text-body text-ink-2">Finished{item.durationMs ? ` in ${fmtDuration(item.durationMs)}` : ''}</div>
      ) : (
        <div className="text-body text-red">Failed: {item.error}</div>
      )
    case 'ask':
      return (
        <div className="text-body text-ink-2">
          Cross-examined {item.asked} agent{item.asked === 1 ? '' : 's'}
          {item.timedOut.length > 0 && <span className="text-amber"> · {item.timedOut.join(', ')} timed out</span>}
        </div>
      )
    case 'proposal':
      return (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-body text-ink">
            <ChevronRight size={14} className="text-ink-3 transition-transform group-open:rotate-90" />
            Submitted {item.edits.length} edit{item.edits.length === 1 ? '' : 's'}
            {item.note && <span className="truncate text-ink-3">· {item.note}</span>}
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {item.edits.map((e, i) => (
              <div key={i} className="rounded-md border border-line px-3 py-2">
                {e.oldText && <div className="font-mono text-meta break-words text-ink-3 line-through">{e.oldText}</div>}
                {e.newText && <div className="font-mono text-meta break-words text-ink">{e.newText}</div>}
                <div className="mt-1 text-body text-ink-2">{e.rationale}</div>
              </div>
            ))}
          </div>
        </details>
      )
  }
}

function ToolGroup({ calls }: { calls: { at: number; name: string; detail?: string }[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-body text-ink-2 hover:text-ink">
        <ChevronRight size={14} className={`text-ink-3 transition-transform ${open ? 'rotate-90' : ''}`} />
        {calls.length} tool call{calls.length === 1 ? '' : 's'}
        {!open && <span className="truncate font-mono text-meta text-ink-3">· {calls.map((c) => c.name).filter((n, i, a) => a.indexOf(n) === i).join(', ')}</span>}
      </button>
      {open && (
        <ol className="mt-1 flex flex-col gap-1 border-l border-line pl-3">
          {calls.map((c, i) => (
            <li key={i} className="font-mono text-meta">
              <span className="text-ink-2">{c.name}</span>{' '}
              <span className="break-words whitespace-pre-wrap text-ink-3">{c.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ raw view */

const FILTERS: { id: string; label: string; kinds: RunEventKind[] | null }[] = [
  { id: 'all', label: 'All', kinds: null },
  { id: 'flow', label: 'Pipeline', kinds: ['log', 'pipeline', 'stage', 'report', 'commit', 'change', 'status'] },
  { id: 'agents', label: 'Agents', kinds: ['agent_start', 'agent_end', 'retry', 'ask_panel', 'proposal'] },
  { id: 'messages', label: 'Messages', kinds: ['message'] },
  { id: 'tools', label: 'Tools', kinds: ['tool', 'tool_result'] },
]

function summary(ev: RunEvent): string {
  switch (ev.kind) {
    case 'log':
      return ev.detail ? `${ev.text} · ${ev.detail}` : ev.text
    case 'pipeline':
      return `attempt ${ev.attempt} · ${ev.agents.length} agents`
    case 'stage':
      return `${ev.stage} ${ev.status}`
    case 'agent_end':
      return ev.ok ? `done ${ev.durationMs ? fmtDuration(ev.durationMs) : ''}` : `error · ${ev.error ?? ''}`
    case 'tool':
    case 'tool_result':
      return `${ev.name} ${ev.detail ?? ''}`
    case 'message':
      return ev.text
    case 'retry':
      return ev.reason
    case 'ask_panel':
      return `${ev.asked} asked · ${ev.timedOut.length} timed out`
    case 'proposal':
      return `${ev.count} edits · ${ev.note ?? ''}`
    case 'report':
      return ev.title ?? ''
    case 'commit':
      return ev.title
    case 'change':
      return `edit ${ev.index + 1}`
    case 'status':
      return ev.status
    case 'agent_start':
      return ''
  }
}

function RawEvents({ model, onClose }: { model: RunModel; onClose: () => void }) {
  const [filter, setFilter] = useState('all')
  const kinds = FILTERS.find((f) => f.id === filter)?.kinds ?? null
  const rows = kinds ? model.events.filter((e) => kinds.includes(e.kind)) : model.events
  return (
    <>
      <DrawerHead title="Event stream" sub={`events.jsonl · ${model.events.length} events`} onClose={onClose}>
        <div className="mt-3 flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-md px-2 py-0.5 text-meta ${filter === f.id ? 'bg-ink/8 text-ink' : 'text-ink-3 hover:text-ink-2'}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </DrawerHead>
      <ol className="flex-1 overflow-y-auto py-2 font-mono text-meta">
        {rows.map((ev, i) => (
          <li key={i} className="grid grid-cols-[48px_96px_96px_minmax(0,1fr)] gap-2 px-5 py-0.5 hover:bg-panel-2">
            <span className="text-right text-ink-3 tabular-nums">{clock(ev.at)}</span>
            <span className="truncate text-ink-2">{ev.kind}</span>
            <span className="truncate text-ink-3">{'agent' in ev ? ev.agent : ''}</span>
            <span className="truncate text-ink-2" title={summary(ev)}>
              {summary(ev)}
            </span>
          </li>
        ))}
      </ol>
    </>
  )
}
