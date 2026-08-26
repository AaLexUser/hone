import { useMemo } from 'react'
import type { AgentState } from '../data'

/**
 * The live SVG graph of the MAJICS pipeline:
 *
 *   traces → [ 3 reviewers ⇄ review judge ] → report → [ 3 proposers ⇄ propose judge ] → commit
 *
 * Every node is one live agent (or artifact); the panel⇄judge edges are the
 * ask_panel cross-examination. Node state follows the event stream — pending,
 * working (pulsing), done, error — and the active stage's group box lights
 * up. Clicking an agent node selects its trace in the activity feed.
 */

export interface StageStates {
  review?: 'start' | 'end'
  propose?: 'start' | 'end'
}

interface Props {
  agents: AgentState[]
  stages: StageStates
  reportReady: boolean
  committed: boolean
  failed: boolean
  selected: string | null
  onSelect: (key: string | null) => void
}

const C = {
  bg: '#0f1114',
  panel2: '#14171b',
  line: '#1d2126',
  line2: '#2a2f36',
  ink: '#eef0f2',
  ink2: '#9da3ad',
  ink3: '#5f6670',
  accent: '#6672e0',
  accent2: '#8b95f6',
  green: '#3dd68c',
  amber: '#ffb224',
  red: '#f2555a',
}

const REVIEW_Y = [86, 160, 234]
const POS = {
  traces: { x: 70, y: 160 },
  reviewBox: { x: 140, y: 30, w: 420, h: 260 },
  reviewers: { x: 250, ys: REVIEW_Y },
  reviewJudge: { x: 500, y: 160 },
  report: { x: 640, y: 160 },
  proposeBox: { x: 720, y: 30, w: 420, h: 260 },
  proposers: { x: 830, ys: REVIEW_Y },
  proposeJudge: { x: 1080, y: 160 },
  commit: { x: 1195, y: 160 },
}

const byStage = (agents: AgentState[], stage: string) => agents.filter((a) => a.stage === stage)

export function PipelineGraph({ agents, stages, reportReady, committed, failed, selected, onSelect }: Props) {
  const review = byStage(agents, 'review')
  const propose = byStage(agents, 'propose')
  const reviewActive = stages.review === 'start'
  const proposeActive = stages.propose === 'start'
  const reviewJudge = review.find((a) => a.role === 'judge')

  const statuses = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.key, a.status])),
    [agents],
  )

  const nodeState = (a?: AgentState) => a?.status ?? 'pending'
  const strokeFor = (state: string) =>
    state === 'error' ? C.red : state === 'done' ? C.green : state === 'working' ? C.accent : C.line2

  return (
    <svg viewBox="0 0 1260 320" className="w-full select-none" style={{ minHeight: 240 }}>
      <style>{`
        @keyframes pg-dash { to { stroke-dashoffset: -16; } }
        @keyframes pg-pulse { 0%,100% { opacity: .9; } 50% { opacity: .25; } }
        .pg-flow { stroke-dasharray: 5 5; animation: pg-dash .8s linear infinite; }
        .pg-working { animation: pg-pulse 1.6s ease-in-out infinite; }
      `}</style>

      {/* ---------------------------------------------------------- group boxes */}
      <GroupBox
        box={POS.reviewBox}
        label="REVIEW"
        active={reviewActive}
        done={stages.review === 'end'}
        sub="3 reviewers ⇄ judge · ask_panel"
      />
      <GroupBox
        box={POS.proposeBox}
        label="PROPOSE"
        active={proposeActive}
        done={stages.propose === 'end'}
        sub="3 proposers ⇄ judge · submit_proposal"
      />

      {/* ---------------------------------------------------------------- edges */}
      {/* traces → reviewers */}
      {POS.reviewers.ys.map((y, i) => (
        <path
          key={`t-r${i}`}
          d={`M ${POS.traces.x + 46} 160 C ${POS.traces.x + 80} 160, ${POS.reviewers.x - 70} ${y}, ${POS.reviewers.x - 20} ${y}`}
          fill="none"
          stroke={reviewActive ? C.accent : C.line2}
          strokeWidth={1.5}
          className={reviewActive ? 'pg-flow' : ''}
          opacity={reviewActive ? 0.9 : 0.7}
        />
      ))}
      {/* reviewers ⇄ review judge (ask_panel cross-examination, both directions) */}
      {POS.reviewers.ys.map((y, i) => (
        <g key={`r-j${i}`}>
          <path
            d={`M ${POS.reviewers.x + 20} ${y} C ${POS.reviewers.x + 130} ${y}, ${POS.reviewJudge.x - 130} 160, ${POS.reviewJudge.x - 24} 160`}
            fill="none"
            stroke={strokeFor(nodeState(review[i])) === C.line2 && !reviewActive ? C.line2 : C.accent}
            strokeWidth={1.5}
            className={reviewActive ? 'pg-flow' : ''}
            opacity={0.85}
          />
          <circle cx={POS.reviewJudge.x - 24} cy={160} r={2.4} fill={reviewActive ? C.accent2 : C.ink3} />
          <circle cx={POS.reviewers.x + 20} cy={y} r={2.4} fill={reviewActive ? C.accent2 : C.ink3} />
        </g>
      ))}
      <EdgeLabel
        x={(POS.reviewers.x + POS.reviewJudge.x) / 2}
        y={100}
        active={reviewActive}
        text="⇄ ask_panel"
      />
      {/* review judge → report */}
      <path
        d={`M ${POS.reviewJudge.x + 24} 160 L ${POS.report.x - 62} 160`}
        fill="none"
        stroke={reportReady ? C.amber : reviewJudge?.status === 'working' ? C.accent : C.line2}
        strokeWidth={1.5}
        className={reviewJudge?.status === 'working' ? 'pg-flow' : ''}
      />
      {/* report → proposers */}
      {POS.proposers.ys.map((y, i) => (
        <path
          key={`rep-p${i}`}
          d={`M ${POS.report.x + 62} 160 C ${POS.report.x + 90} 160, ${POS.proposers.x - 70} ${y}, ${POS.proposers.x - 20} ${y}`}
          fill="none"
          stroke={proposeActive ? C.accent : C.line2}
          strokeWidth={1.5}
          className={proposeActive ? 'pg-flow' : ''}
          opacity={proposeActive ? 0.9 : 0.7}
        />
      ))}
      {/* proposers ⇄ propose judge (ask_panel cross-examination) */}
      {POS.proposers.ys.map((y, i) => (
        <g key={`p-j${i}`}>
          <path
            d={`M ${POS.proposers.x + 20} ${y} C ${POS.proposers.x + 130} ${y}, ${POS.proposeJudge.x - 130} 160, ${POS.proposeJudge.x - 24} 160`}
            fill="none"
            stroke={proposeActive ? C.accent : C.line2}
            strokeWidth={1.5}
            className={proposeActive ? 'pg-flow' : ''}
            opacity={0.85}
          />
          <circle cx={POS.proposeJudge.x - 24} cy={160} r={2.4} fill={proposeActive ? C.accent2 : C.ink3} />
          <circle cx={POS.proposers.x + 20} cy={y} r={2.4} fill={proposeActive ? C.accent2 : C.ink3} />
        </g>
      ))}
      <EdgeLabel
        x={(POS.proposers.x + POS.proposeJudge.x) / 2}
        y={100}
        active={proposeActive}
        text="⇄ ask_panel"
      />
      {/* propose judge → commit */}
      <path
        d={`M ${POS.proposeJudge.x + 24} 160 L ${POS.commit.x - 36} 160`}
        fill="none"
        stroke={committed ? C.green : proposeActive ? C.accent : C.line2}
        strokeWidth={1.5}
        className={proposeActive && !committed ? 'pg-flow' : ''}
      />

      {/* --------------------------------------------------------------- nodes */}
      <IoNode
        x={POS.traces.x}
        y={POS.traces.y}
        label="Traces"
        sub="frozen batch"
        state={review.length ? (stages.review ? 'done' : 'working') : 'pending'}
      />
      {review
        .filter((a) => a.role !== 'judge')
        .map((a, i) => (
          <AgentNode
            key={a.key}
            agent={a}
            x={POS.reviewers.x}
            y={POS.reviewers.ys[i] ?? 160}
            selected={selected === a.key}
            onSelect={onSelect}
          />
        ))}
      {reviewJudge && (
        <AgentNode
          agent={reviewJudge}
          x={POS.reviewJudge.x}
          y={POS.reviewJudge.y}
          r={24}
          selected={selected === reviewJudge.key}
          onSelect={onSelect}
        />
      )}
      <IoNode
        x={POS.report.x}
        y={POS.report.y}
        label="Report"
        sub={reportReady ? 'html · ready' : 'judge output'}
        state={reportReady ? 'done' : reviewJudge?.status === 'working' ? 'working' : 'pending'}
        accent={reportReady ? C.amber : undefined}
      />
      {propose
        .filter((a) => a.role !== 'judge')
        .map((a, i) => (
          <AgentNode
            key={a.key}
            agent={a}
            x={POS.proposers.x}
            y={POS.proposers.ys[i] ?? 160}
            selected={selected === a.key}
            onSelect={onSelect}
          />
        ))}
      {(() => {
        const pj = propose.find((a) => a.role === 'judge')
        return pj ? (
          <AgentNode
            agent={pj}
            x={POS.proposeJudge.x}
            y={POS.proposeJudge.y}
            r={24}
            selected={selected === pj.key}
            onSelect={onSelect}
          />
        ) : null
      })()}
      <IoNode
        x={POS.commit.x}
        y={POS.commit.y}
        label="Commit"
        sub={committed ? 'applied' : failed ? 'rejected' : 'verify · apply'}
        state={committed ? 'done' : failed ? 'error' : proposeActive ? 'working' : 'pending'}
        w={78}
      />

      {/* status labels for unseen agents (replay before the pipeline event) */}
      {agents.length === 0 && (
        <text x={630} y={168} textAnchor="middle" fill={C.ink3} fontSize={12}>
          waiting for the pipeline to start…
        </text>
      )}
      {Object.entries(statuses).length === 0 && null}
    </svg>
  )
}

/* ------------------------------------------------------------------ pieces */

/** A small mono label on a group's ⇄ edges, naming the MAJICS
 *  cross-examination that flows along them. */
function EdgeLabel({ x, y, text, active }: { x: number; y: number; text: string; active: boolean }) {
  return (
    <g>
      <rect
        x={x - 34}
        y={y - 9}
        width={68}
        height={16}
        rx={8}
        fill={C.bg}
        stroke={active ? C.accent : C.line2}
        strokeOpacity={active ? 0.6 : 1}
        strokeWidth={1}
      />
      <text
        x={x}
        y={y + 3}
        textAnchor="middle"
        fill={active ? C.accent2 : C.ink3}
        fontSize={9.5}
        fontFamily="JetBrains Mono, monospace"
      >
        {text}
      </text>
    </g>
  )
}

function GroupBox({
  box,
  label,
  sub,
  active,
  done,
}: {
  box: { x: number; y: number; w: number; h: number }
  label: string
  sub: string
  active: boolean
  done: boolean
}) {
  return (
    <g>
      <rect
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={12}
        fill={C.bg}
        fillOpacity={active ? 0.75 : 0.45}
        stroke={active ? C.accent : done ? C.green : C.line}
        strokeOpacity={active ? 0.5 : done ? 0.35 : 1}
        strokeWidth={active ? 1.5 : 1}
        className={active ? 'pg-working' : ''}
      />
      <text
        x={box.x + 14}
        y={box.y + 22}
        fill={active ? C.accent2 : done ? C.green : C.ink3}
        fontSize={11}
        fontWeight={600}
        letterSpacing={1.4}
      >
        {label}
      </text>
      <text x={box.x + 14} y={box.y + 37} fill={C.ink3} fontSize={9.5} fontFamily="JetBrains Mono, monospace">
        {sub}
      </text>
    </g>
  )
}

function AgentNode({
  agent,
  x,
  y,
  r = 20,
  selected,
  onSelect,
}: {
  agent: AgentState
  x: number
  y: number
  r?: number
  selected: boolean
  onSelect: (key: string | null) => void
}) {
  const stroke =
    agent.status === 'error' ? C.red : agent.status === 'done' ? C.green : agent.status === 'working' ? agent.color : C.line2
  const short = agent.model.split('/').pop() ?? agent.model
  return (
    <g
      onClick={() => onSelect(selected ? null : agent.key)}
      style={{ cursor: 'pointer' }}
      opacity={agent.status === 'pending' ? 0.65 : 1}
    >
      {agent.status === 'working' && (
        <circle cx={x} cy={y} r={r + 5} fill="none" stroke={agent.color} strokeWidth={1.5} className="pg-working" />
      )}
      {selected && <circle cx={x} cy={y} r={r + 4} fill="none" stroke={C.accent2} strokeWidth={1.5} />}
      <circle cx={x} cy={y} r={r} fill={C.panel2} stroke={stroke} strokeWidth={agent.status === 'pending' ? 1 : 1.5} />
      {/* role key inside: r1..r3 / j · p1..p3 */}
      <text
        x={x}
        y={y + 3.5}
        textAnchor="middle"
        fill={agent.status === 'pending' ? C.ink3 : C.ink}
        fontSize={agent.role === 'judge' ? 12 : 11}
        fontWeight={600}
        fontFamily="JetBrains Mono, monospace"
      >
        {agent.role === 'judge' ? 'J' : agent.key.split('-')[1]}
      </text>
      <text x={x} y={y + r + 15} textAnchor="middle" fill={C.ink3} fontSize={9.5} fontFamily="JetBrains Mono, monospace">
        {short}
      </text>
      {agent.status === 'done' && (
        <circle cx={x + r - 6} cy={y - r + 6} r={4} fill={C.bg} stroke={C.green} strokeWidth={1.2} />
      )}
      {agent.status === 'error' && (
        <circle cx={x + r - 6} cy={y - r + 6} r={4} fill={C.bg} stroke={C.red} strokeWidth={1.2} />
      )}
      <title>
        {agent.key} · {agent.model}
        {agent.error ? ` — ${agent.error}` : agent.durationMs ? ` · ${(agent.durationMs / 1000).toFixed(1)}s` : ''}
      </title>
    </g>
  )
}

function IoNode({
  x,
  y,
  label,
  sub,
  state,
  w = 118,
  accent,
}: {
  x: number
  y: number
  label: string
  sub: string
  state: string
  w?: number
  accent?: string
}) {
  const stroke =
    state === 'error' ? C.red : state === 'done' ? accent ?? C.green : state === 'working' ? C.accent : C.line2
  const h = 44
  return (
    <g opacity={state === 'pending' ? 0.65 : 1}>
      {state === 'working' && (
        <rect
          x={x - w / 2 - 4}
          y={y - h / 2 - 4}
          width={w + 8}
          height={h + 8}
          rx={10}
          fill="none"
          stroke={C.accent}
          strokeWidth={1.2}
          className="pg-working"
        />
      )}
      <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx={8} fill={C.panel2} stroke={stroke} strokeWidth={1.2} />
      <text x={x} y={y - 2} textAnchor="middle" fill={C.ink} fontSize={11.5} fontWeight={600}>
        {label}
      </text>
      <text x={x} y={y + 13} textAnchor="middle" fill={C.ink3} fontSize={8.5} fontFamily="JetBrains Mono, monospace">
        {sub}
      </text>
    </g>
  )
}
