import type { RunOutcome } from '../data'

/**
 * The run's event stream (`/api/runs/:id/events`, one events.jsonl line per
 * frame), parsed once at the boundary into a discriminated union. Everything
 * past `parseRunEvent` trusts these shapes.
 */

export type Stage = 'review' | 'propose'

export interface RosterEntry {
  key: string
  model: string
  role: 'reviewer' | 'proposer' | 'judge'
  stage: Stage
}

/** One question the judge sent through ask_panel, to the panel seat `role`. */
export interface AskQuery {
  role: string
  question: string
}

export interface DraftEdit {
  oldText: string
  newText: string
  rationale: string
  evidence: string[]
}

export type RunEvent =
  | { kind: 'log'; at: number; icon?: string; text: string; detail?: string }
  | { kind: 'pipeline'; at: number; attempt: number; agents: RosterEntry[] }
  | { kind: 'stage'; at: number; stage: Stage; status: 'start' | 'end' }
  | { kind: 'agent_start'; at: number; agent: string }
  | { kind: 'agent_end'; at: number; agent: string; ok: boolean; durationMs?: number; error?: string }
  | { kind: 'tool'; at: number; agent: string; name: string; detail?: string; queries?: AskQuery[] }
  | { kind: 'tool_result'; at: number; agent: string; name: string; detail?: string }
  | { kind: 'message'; at: number; agent: string; text: string }
  | { kind: 'retry'; at: number; agent: string; reason: string }
  | { kind: 'ask_panel'; at: number; agent: string; stage: Stage; durationMs: number; asked: number; timedOut: string[] }
  | { kind: 'proposal'; at: number; agent: string; count: number; note?: string; edits: DraftEdit[] }
  | { kind: 'report'; at: number; title?: string }
  | { kind: 'commit'; at: number; title: string }
  | { kind: 'change'; at: number; index: number }
  | { kind: 'status'; at: number; status: RunOutcome }

export type RunEventKind = RunEvent['kind']

type Raw = Record<string, unknown>

const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined)
const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const stage = (v: unknown): Stage | undefined => (v === 'review' || v === 'propose' ? v : undefined)

const OUTCOMES: readonly RunOutcome[] = ['running', 'validating', 'succeeded', 'failed', 'no-changes']
const ROLES: readonly RosterEntry['role'][] = ['reviewer', 'proposer', 'judge']

function rosterEntry(v: unknown): RosterEntry | null {
  if (!v || typeof v !== 'object') return null
  const r = v as Raw
  const key = str(r.key)
  const s = stage(r.stage)
  const role = ROLES.find((x) => x === r.role)
  if (!key || !s || !role) return null
  return { key, model: str(r.model) ?? '', role, stage: s }
}

function askQuery(v: unknown): AskQuery | null {
  if (!v || typeof v !== 'object') return null
  const r = v as Raw
  const role = str(r.role)
  const question = str(r.question)
  return role && question ? { role, question } : null
}

function draftEdit(v: unknown): DraftEdit | null {
  if (!v || typeof v !== 'object') return null
  const r = v as Raw
  return {
    oldText: str(r.oldText) ?? '',
    newText: str(r.newText) ?? '',
    rationale: str(r.rationale) ?? '',
    evidence: strs(r.evidence),
  }
}

/** One SSE frame to a typed event; frames this page has no use for return null. */
export function parseRunEvent(data: string): RunEvent | null {
  let r: Raw
  try {
    const parsed: unknown = JSON.parse(data)
    if (!parsed || typeof parsed !== 'object') return null
    r = parsed as Raw
  } catch {
    return null
  }
  const at = num(r.at) ?? 0
  const agent = str(r.agent)
  switch (r.kind) {
    case 'log':
      return { kind: 'log', at, icon: str(r.icon), text: str(r.text) ?? '', detail: str(r.detail) }
    case 'pipeline': {
      const agents = Array.isArray(r.agents) ? r.agents.map(rosterEntry).filter((a) => a !== null) : []
      return { kind: 'pipeline', at, attempt: num(r.attempt) ?? 1, agents }
    }
    case 'stage': {
      const s = stage(r.stage)
      if (!s) return null
      return { kind: 'stage', at, stage: s, status: r.status === 'end' ? 'end' : 'start' }
    }
    case 'agent_start':
      return agent ? { kind: 'agent_start', at, agent } : null
    case 'agent_end':
      return agent
        ? { kind: 'agent_end', at, agent, ok: r.status !== 'error', durationMs: num(r.durationMs), error: str(r.error) }
        : null
    case 'tool': {
      const queries = Array.isArray(r.queries) ? r.queries.map(askQuery).filter((q) => q !== null) : undefined
      return agent ? { kind: 'tool', at, agent, name: str(r.name) ?? 'tool', detail: str(r.detail), queries } : null
    }
    case 'tool_result':
      return agent ? { kind: 'tool_result', at, agent, name: str(r.name) ?? 'tool', detail: str(r.detail) } : null
    case 'message':
      return agent ? { kind: 'message', at, agent, text: str(r.text) ?? '' } : null
    case 'retry':
      return agent ? { kind: 'retry', at, agent, reason: str(r.reason) ?? 'retry' } : null
    case 'analytics': {
      const s = stage(r.stage)
      if (r.name !== 'ask_panel' || !agent || !s) return null
      return {
        kind: 'ask_panel',
        at,
        agent,
        stage: s,
        durationMs: num(r.durationMs) ?? 0,
        asked: num(r.workersAsked) ?? 0,
        timedOut: strs(r.timedOutRoles),
      }
    }
    case 'proposal': {
      const edits = Array.isArray(r.edits) ? r.edits.map(draftEdit).filter((e) => e !== null) : []
      return agent ? { kind: 'proposal', at, agent, count: num(r.count) ?? edits.length, note: str(r.note), edits } : null
    }
    case 'report':
      return { kind: 'report', at, title: str(r.title) }
    case 'commit':
      return { kind: 'commit', at, title: str(r.title) ?? '' }
    case 'change': {
      const index = num(r.index)
      return index === undefined ? null : { kind: 'change', at, index }
    }
    case 'status': {
      const status = OUTCOMES.find((o) => o === r.status)
      return status ? { kind: 'status', at, status } : null
    }
    default:
      return null
  }
}
