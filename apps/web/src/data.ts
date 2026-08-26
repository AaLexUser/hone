export type TraceStatus = 'new' | 'analyzed'

export interface Trace {
  id: string
  firstLine: string
  receivedAt: number
  turns: number
  /** Human feedback, or runner-generated `Expected: … Got: …` on benchmark mismatches. */
  feedback?: string
  status: TraceStatus
  versionId: string
}

export interface VersionNode {
  id: string
  parentId: string | null
  /** All parents — two for a merge commit, one for a normal commit. */
  parents?: string[]
  createdAt: number
  runId: string | null
  file: string[]
  /** Git branch this commit belongs to — drives the graph lane and its color. */
  branch: string
  lane: number
  /** Conventional-commit title the optimizer (or merge) authored. */
  title?: string | null
}

/** A real branch in the AGENTS.md git repository. */
export interface BranchInfo {
  name: string
  tip: string
  lane: number
  color: string
  count: number
  current: boolean
}

export interface ConversationTurn {
  role: 'user' | 'assistant' | 'tool'
  text: string
  tool?: { name: string; args: string; result: string }
}

export interface ProposedChange {
  op: 'insert' | 'update' | 'delete'
  section: string
  line: number
  before?: string
  after?: string
  rationale: string
  evidence: string[]
}

export type LogIcon = 'start' | 'read' | 'scan' | 'note' | 'draft' | 'check' | 'retry' | 'fail'

/** One seat in the MAJICS pipeline: a reviewer, a proposer, or a judge. */
export interface PipelineAgent {
  key: string
  model: string
  role: 'reviewer' | 'proposer' | 'judge'
  stage: 'review' | 'propose'
  color: string
}

export type AgentStatus = 'pending' | 'working' | 'done' | 'error'

/** Live state of one pipeline agent, derived from the run's event stream. */
export interface AgentState extends PipelineAgent {
  status: AgentStatus
  durationMs?: number
  error?: string
  usage?: Record<string, number>
}

/**
 * An optimizer activity event in the run timeline. `log` events come from the
 * service; the pipeline streams the rest live — `tool` / `tool_result` /
 * `message` / `proposal` carry the emitting `agent`, `agent_start` /
 * `agent_end` bracket one pipeline agent, `stage` marks the review and
 * propose stages, and `report` announces the review judge's HTML report.
 */
export interface LogEvent {
  at: number
  kind:
    | 'log'
    | 'feedback'
    | 'agent'
    | 'tool'
    | 'tool_result'
    | 'commit'
    | 'message'
    | 'proposal'
    | 'agent_start'
    | 'agent_end'
    | 'stage'
    | 'report'
    | 'analytics'
    | 'pipeline'
  icon?: LogIcon
  text?: string
  detail?: string
  /** Name of the tool that produced a tool / tool_result event. */
  name?: string
  /** The pipeline agent that emitted this event. */
  agent?: string
  /** Colors the icon chip — verifier rejections and hard failures. */
  level?: 'warn' | 'error'
  /** commit events carry the judge-authored message. */
  title?: string
  body?: string
  /** agent_end events. */
  status?: string
  durationMs?: number
  error?: string
  usage?: Record<string, number>
  /** ask_panel analytics events. */
  workersAsked?: number
  workersTimedOut?: number
  timedOutRoles?: string[]
  queriesAsked?: number
  queriesTimedOut?: number
  timeoutMs?: number
  /** message events: the agent's finished text for one turn. */
  model?: string
  role?: string
  stage?: string
  /** proposal events. */
  count?: number
  note?: string
  edits?: { oldText: string; newText: string; rationale: string; evidence: string[] }[]
  /** pipeline events. */
  attempt?: number
  agents?: PipelineAgent[]
  /** report events. */
  bytes?: number
}

export type RunEvent =
  | LogEvent
  | { at: number; kind: 'change'; index: number }
  | { at: number; kind: 'status'; status: RunOutcome }

export type RunOutcome = 'running' | 'validating' | 'succeeded' | 'failed' | 'no-changes'

/** One optimizer run — everything the run page needs to be replayed read-only. */
export interface RunRecord {
  id: string
  status: RunOutcome
  trigger: 'manual' | 'auto'
  startedAt: number
  durationMs: number
  model: string
  attempts: number
  traceIds: string[]
  baseVersionId: string
  resultVersionId: string | null
  /** Why the run produced no version, for `failed` / `no-changes`. */
  note?: string
  changes: ProposedChange[]
  events: LogEvent[]
  /** The judge-authored commit this run produced, when it succeeded. */
  commitTitle?: string | null
  commitBody?: string | null
  commitBranch?: string | null
  /** The review judge's HTML report exists for this run. */
  hasReport?: boolean
}

/* ----------------------------------------------------------- version tree */

/**
 * Fallback palette for branch colors when the backend payload is not loaded
 * yet. Live colors come from /api/state, keyed by branch name; branches past
 * the brand set get unique generated hues there (golden-angle walk).
 */
export const palette = [
  '#6672e0', '#2fbcb0', '#d99a3c', '#b06ee8', '#4aa3f0', '#e5736e',
]

export const colorOf = (branch: string, branches: BranchInfo[] = []) =>
  branches.find((b) => b.name === branch)?.color ?? palette[0]
