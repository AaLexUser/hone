import type { Stage } from './events'
import type { RunModel, Seat, Span } from './model'
import { VERDICT_LOG } from './model'
import { attemptStories } from './derive'
import type { AttemptStory } from './derive'

/**
 * The activity feed folded from the event stream into story rows: one row per
 * stretch of agent work with its tool calls grouped inside, the judge's
 * follow-up questions with the answers nested under them, and a handful of
 * pipeline milestones. Raw events stay in the drawer.
 */

export interface ToolCall {
  name: string
  detail?: string
}

export interface WorkRow {
  type: 'work'
  id: string
  seat: Seat
  span: Span
  tools: ToolCall[]
  text: string | null
  drafted: number | null
  retries: number
  /** The stage window this work ran in, for its little time bar. */
  window: [number, number | null]
}

/** One exchange in a cross-examination. Runs recorded before questions were kept have answers only. */
export interface AskTurn {
  seat: Seat
  question: string | null
  answer: WorkRow | null
}

export interface AskRow {
  type: 'ask'
  id: string
  judge: Seat
  at: number
  end: number | null
  turns: AskTurn[]
  timedOut: string[]
}

export type Milestone =
  | { type: 'stage'; id: string; at: number; stage: Stage; attempt: number }
  | { type: 'batch'; id: string; at: number; sessions: number }
  | { type: 'report'; id: string; at: number }
  | { type: 'failed'; id: string; at: number; story: AttemptStory }
  | { type: 'commit'; id: string; at: number; title: string }

export type Row = WorkRow | AskRow | Milestone

/** The first line of an agent message that says something, without markdown headings. */
export function gist(text: string): string {
  return (
    text
      .split('\n')
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith('#')) ?? ''
  )
}

const NAMED: Record<string, string> = {
  submit_review: 'submit the review',
  submit_proposal: 'submit the proposal',
  ask_panel: 'ask the panel',
}

/** The file a shell command reads or searches: `traces/*.jsonl` reads as `traces`, `/app/workspace/agents.md` as `agents.md`. */
function target(args: string[]): string | null {
  const path = args.filter((a) => !a.startsWith('-') && /[/*]|\.\w+$/.test(a) && !/^['"]/.test(a)).at(-1)
  if (!path) return null
  if (path.includes('*')) return path.split('/').filter((p) => p && !p.includes('*')).at(-1) ?? null
  const file = path.split('/').at(-1) ?? ''
  // A session's trace file reads as its id; a cut-off name keeps what is certain.
  return /\.jsonl$|…$/.test(file) ? file.split('.')[0] : file
}

/**
 * A tool call in a few plain words for the activity row: `read agents.md`,
 * `python3 (inline script)`, `search traces`. The raw command stays in the drawer.
 */
export function toolGist({ name, detail }: ToolCall): string {
  if (name !== 'bash') return NAMED[name] ?? name.replace(/_/g, ' ')
  const cmd = (detail ?? '')
    .replace(/'[^']*'|"[^"]*"/g, "''")
    .split(/\s*(?:\||&&|;)\s*/)[0]
    .trim()
  const [bin = '', ...args] = cmd.split(/\s+/)
  if (/^python3?$/.test(bin)) {
    const script = args.find((a) => a.endsWith('.py'))
    return script ? `python3 ${script.split('/').at(-1)}` : 'python3 (inline script)'
  }
  const file = target(args)
  if (/^(cat|head|tail|less|sed|nl|wc)$/.test(bin)) return file ? `read ${file}` : 'read a file'
  if (/^(grep|rg|egrep)$/.test(bin)) return file ? `search ${file}` : 'search'
  if (bin === 'ls' || bin === 'find') return file ? `list ${file}` : 'list files'
  if (bin === 'jq') return file ? `query ${file}` : 'query json'
  return bin ? `${bin} (shell)` : 'shell command'
}

export function activityRows(m: RunModel): Row[] {
  const rows: Row[] = []
  const open = new Map<string, WorkRow>()
  const lastWork = new Map<string, WorkRow>()
  let ask: AskRow | null = null
  const seatOf = (key: string) => m.seats.find((s) => s.key === key)
  const stories = attemptStories(m)
  let window: [number, number | null] = [0, null]
  let attempt = 1

  for (const [i, ev] of m.events.entries()) {
    const id = `${ev.kind}-${i}`
    switch (ev.kind) {
      case 'pipeline':
        attempt = ev.attempt
        break
      case 'stage': {
        const w = m.windows.find((x) => x.stage === ev.stage && x.start === ev.at)
        if (ev.status === 'start') {
          window = [ev.at, w?.end ?? null]
          rows.push({ type: 'stage', id, at: ev.at, stage: ev.stage, attempt })
        }
        break
      }
      case 'log': {
        if (ev.text === 'Batch frozen') {
          rows.push({ type: 'batch', id, at: ev.at, sessions: ev.detail ? ev.detail.split(',').length : 0 })
        }
        const failed = VERDICT_LOG.exec(ev.text)
        const story = failed && stories.find((s) => s.n === Number(failed[1]))
        if (story) rows.push({ type: 'failed', id, at: ev.at, story })
        break
      }
      case 'agent_start': {
        const seat = seatOf(ev.agent)
        const span = m.lanes[ev.agent]?.spans.find((s) => s.start === ev.at)
        if (!seat || !span) break
        const row: WorkRow = { type: 'work', id, seat, span, tools: [], text: null, drafted: null, retries: 0, window }
        open.set(ev.agent, row)
        lastWork.set(ev.agent, row)
        if (span.followUp && ask) {
          const turn = ask.turns.find((t) => t.seat.key === ev.agent && !t.answer)
          if (turn) turn.answer = row
          else ask.turns.push({ seat, question: null, answer: row })
        } else rows.push(row)
        break
      }
      case 'tool': {
        if (ev.name === 'ask_panel') {
          const judge = seatOf(ev.agent)
          if (judge) {
            const turns = (ev.queries ?? []).flatMap((q) => {
              const seat = seatOf(q.role)
              return seat ? [{ seat, question: q.question, answer: null }] : []
            })
            ask = { type: 'ask', id, judge, at: ev.at, end: null, turns, timedOut: [] }
            rows.push(ask)
          }
          break
        }
        open.get(ev.agent)?.tools.push({ name: ev.name, detail: ev.detail })
        break
      }
      case 'ask_panel':
        if (ask) ask.timedOut = ev.timedOut
        break
      case 'tool_result':
        if (ev.name === 'ask_panel' && ask) {
          ask.end = ev.at
          ask = null
        }
        break
      case 'message': {
        const row = open.get(ev.agent) ?? lastWork.get(ev.agent)
        if (row) row.text = ev.text
        break
      }
      case 'retry': {
        const row = open.get(ev.agent)
        if (row) row.retries++
        break
      }
      case 'proposal': {
        const row = lastWork.get(ev.agent)
        if (row) row.drafted = ev.edits.length
        break
      }
      case 'agent_end':
        open.delete(ev.agent)
        break
      case 'report':
        rows.push({ type: 'report', id, at: ev.at })
        break
      case 'commit':
        rows.push({ type: 'commit', id, at: ev.at, title: ev.title })
        break
    }
  }
  return rows
}
