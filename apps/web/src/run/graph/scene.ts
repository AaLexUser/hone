import type { Stage } from '../events'
import type { RunModel, Seat } from '../model'
import { crossExam, seatStatus, stageState, verifyState } from '../derive'
import type { Cross, LaneStatus, StageState, VerifyState } from '../derive'
import { left, right } from './layout'
import type { GraphLayout, Rect, Wire } from './layout'

/** What each card and edge of the graph shows, folded from the model; the component only draws it. */

export type NodeState = 'idle' | 'working' | 'done' | 'error' | 'skipped'

export interface SeatNode {
  seat: Seat
  box: Rect
  state: NodeState
  cross: Cross | null
}

export type EdgeState = 'idle' | 'active' | 'done' | 'cross'

export interface Edge {
  id: string
  wire: Wire
  state: EdgeState
  /** A calm flow runs along this edge while the work it feeds is running. */
  flow: boolean
}

export interface GroupScene {
  stage: Stage
  state: StageState
  seats: SeatNode[]
  /** The judge has an ask_panel follow-up open right now. */
  asking: boolean
}

export interface Scene {
  groups: GroupScene[]
  edges: Edge[]
  traces: NodeState
  report: NodeState
  verify: NodeState
  commit: NodeState
}

const NODE: Record<LaneStatus, NodeState> = { idle: 'idle', running: 'working', done: 'done', error: 'error' }

const VERIFY: Record<VerifyState, NodeState> = {
  pending: 'idle',
  active: 'working',
  passed: 'done',
  rejected: 'error',
  skipped: 'skipped',
}

const mid = (a: number, b: number) => Math.round((a + b) / 2)

export function scene(m: RunModel, layout: GraphLayout): Scene {
  const edges: Edge[] = []
  const groups = layout.groups.map((g): GroupScene => {
    const state = stageState(m, g.stage)
    const cross = crossExam(m, g.stage)
    const judgeState: NodeState = g.judge ? NODE[seatStatus(m, g.judge.seat)] : 'idle'
    const source = g.stage === 'review' ? layout.traces : layout.report
    const firstPanel = g.panel[0]?.box
    const xmIn = firstPanel ? mid(source.x + source.w, firstPanel.x) : 0
    const xmOut = firstPanel && g.judge ? mid(firstPanel.x + firstPanel.w, g.judge.box.x) : 0
    const asking = m.followUps.some((f) => f.stage === g.stage && f.end === null)
    const seats: SeatNode[] = g.panel.map(({ seat, box }) => {
      const st = NODE[seatStatus(m, seat)]
      const c = cross[seat.key] ?? null
      const answering = !!c?.live
      const live = st === 'working' && !answering
      edges.push({
        id: `in:${seat.key}`,
        wire: { a: right(source), b: left(box), xm: xmIn },
        state: live ? 'active' : state === 'pending' || state === 'skipped' ? 'idle' : 'done',
        flow: live,
      })
      if (g.judge) {
        const fusing = judgeState === 'working' && !asking
        edges.push({
          id: `out:${seat.key}`,
          wire: { a: right(box), b: left(g.judge.box), xm: xmOut },
          state: answering || fusing ? 'active' : c ? 'cross' : st === 'done' ? 'done' : 'idle',
          flow: answering || fusing,
        })
      }
      return { seat, box, state: st, cross: c }
    })
    if (g.judge) {
      seats.push({ seat: g.judge.seat, box: g.judge.box, state: judgeState, cross: cross[g.judge.seat.key] ?? null })
    }
    return { stage: g.stage, state, seats, asking }
  })

  const [review, propose] = layout.groups
  const reportReady = m.reportAt !== null
  const reviewJudge = groups[0].seats.find((s) => s.seat.judge)
  const verify = verifyState(m)
  const straight = (a: Rect, b: Rect): Wire => ({ a: right(a), b: left(b), xm: 0 })
  if (review.judge) {
    edges.push({
      id: 'judge:review',
      wire: straight(review.judge.box, layout.report),
      state: reportReady ? 'done' : reviewJudge?.state === 'working' ? 'active' : 'idle',
      flow: false,
    })
  }
  if (propose.judge) {
    edges.push({
      id: 'judge:propose',
      wire: straight(propose.judge.box, layout.verify),
      state: verify === 'active' ? 'active' : verify === 'passed' || verify === 'rejected' ? 'done' : 'idle',
      flow: verify === 'active',
    })
  }
  edges.push({
    id: 'verify',
    wire: straight(layout.verify, layout.commit),
    state: m.outcome === 'succeeded' ? 'done' : 'idle',
    flow: false,
  })

  return {
    groups,
    edges,
    traces: m.seats.length ? 'done' : 'working',
    report: reportReady ? 'done' : reviewJudge?.state === 'working' ? 'working' : 'idle',
    verify: VERIFY[verify],
    commit: m.outcome === 'succeeded' ? 'done' : m.outcome === 'failed' || m.outcome === 'no-changes' ? 'skipped' : 'idle',
  }
}
