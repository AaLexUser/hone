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
  before?: string | null
  after?: string | null
  rationale: string
  evidence: string[]
}

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
  /** The judge-authored commit this run produced, when it succeeded. */
  commitTitle?: string | null
  commitBody?: string | null
  commitBranch?: string | null
  /** The review judge's HTML report exists for this run. */
  hasReport?: boolean
}

/** One finding or hypothesis from the review judge's review.json. */
export interface ReviewItem {
  statement: string
  traceIds: string[]
  confidence: 'high' | 'medium' | 'low'
}

/** `GET /api/runs/:id/review`: the structured data behind the review report. */
export interface Review {
  summary: string
  findings: ReviewItem[]
  hypotheses: ReviewItem[]
  unresolved: string[]
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
