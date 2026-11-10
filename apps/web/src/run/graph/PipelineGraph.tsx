import type { KeyboardEvent, ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { RunModel } from '../model'
import { attemptStories, laneGroups, panelNoun, shortModel } from '../derive'
import type { AttemptStory, StageState } from '../derive'
import { CARD_H, TEXT_X, graphLayout, wirePath, wirePoints } from './layout'
import type { Rect, Wire } from './layout'
import { scene } from './scene'
import type { Edge, GroupScene, NodeState, SeatNode } from './scene'
import { usePulses } from './usePulses'
import type { Pulse, Shake } from './usePulses'

/**
 * The MAJICS pipeline as cards, built from the roster: Traces → REVIEW (K
 * reviewers → judge) → Report → PROPOSE (M proposers → judge) → Verify →
 * Commit. Each card carries a status icon; edges are orthogonal and share a
 * trunk; motion marks what is happening now.
 */

export interface GraphProps {
  model: RunModel
  sessions: { id: string; feedback: boolean }[]
  findings: number | null
  commitId: string | null
  selected: string | null
  onSelect: (key: string) => void
  /** False while the backlog replays, so a finished run renders at rest. */
  animate: boolean
}

const EASE = [0.22, 1, 0.36, 1] as const
const ICON = { x: 17, r: 8 }

export function PipelineGraph({ model, sessions, findings, commitId, selected, onSelect, animate }: GraphProps) {
  const reduce = useReducedMotion() ?? false
  const moving = animate && !reduce
  const layout = graphLayout(laneGroups(model))
  const s = scene(model, layout)
  const { pulses, shakes, done } = usePulses(model, moving)
  const edges = new Map(s.edges.map((e) => [e.id, e]))
  const stories = attemptStories(model)

  return (
    <svg viewBox={`0 0 ${layout.w} ${layout.h}`} className="block w-full select-none" role="img" aria-label="MAJICS pipeline">
      {layout.groups.map((g, i) => (
        <Section key={g.stage} box={g.box} group={s.groups[i]} seats={g.panel.length} attempts={g.stage === 'propose' ? stories : []} />
      ))}

      {s.edges.map((e) => (
        <path key={e.id} d={wirePath(e.wire)} fill="none" strokeWidth={1.5} className="stroke-line-2" />
      ))}
      {[...s.edges]
        .filter((e) => e.state !== 'idle')
        .sort((a, b) => EDGE_ORDER[a.state] - EDGE_ORDER[b.state])
        .map((e) => (
          <EdgeOverlay key={e.id} edge={e} moving={moving} reduce={reduce} />
        ))}

      <Card box={layout.traces} state={s.traces} name="Traces" title={`${sessions.length} sessions in the frozen batch`} moving={moving}>
        <SessionDots sessions={sessions} />
      </Card>
      <Pop on={s.report === 'done'} moving={moving}>
        <Card box={layout.report} state={s.report} name="Report" title="The review judge's report" tone="amber" moving={moving}>
          {findings !== null && <Sub>{`${findings} ${findings === 1 ? 'finding' : 'findings'}`}</Sub>}
        </Card>
      </Pop>
      <Card box={layout.verify} state={s.verify} name="Verify" title="Every edit must anchor in AGENTS.md and cite real sessions" moving={moving}>
        {VERIFY_SUB[s.verify] && <Sub>{VERIFY_SUB[s.verify]}</Sub>}
      </Card>
      <Pop on={s.commit === 'done'} moving={moving}>
        <Card box={layout.commit} state={s.commit} name="Commit" title="A new AGENTS.md version" moving={moving}>
          {commitId && <Sub mono>{commitId}</Sub>}
        </Card>
      </Pop>

      {s.groups.flatMap((g) =>
        g.seats.map((n) => (
          <SeatCard
            key={n.seat.key}
            node={n}
            asking={g.asking}
            selected={selected === n.seat.key}
            shake={shakes[n.seat.key]}
            moving={moving}
            onSelect={onSelect}
          />
        )),
      )}

      {pulses.map((p) => {
        const e = edges.get(p.edge)
        return e ? <PulseDot key={p.id} pulse={p} wire={e.wire} onDone={done} /> : null
      })}
    </svg>
  )
}

const VERIFY_SUB: Record<NodeState, string | null> = {
  idle: null,
  working: 'checking',
  done: 'passed',
  error: 'rejected',
  skipped: 'not run',
}

/* ---------------------------------------------------------------- sections */

const STATE_WORD: Record<StageState, { word: string; cls: string }> = {
  pending: { word: 'queued', cls: 'fill-ink-3' },
  skipped: { word: 'skipped', cls: 'fill-ink-3' },
  active: { word: 'running', cls: 'fill-accent-2' },
  done: { word: 'done', cls: 'fill-green' },
  retry: { word: 'retrying', cls: 'fill-amber' },
  failed: { word: 'failed', cls: 'fill-red' },
}

const FRAME: Record<StageState, string> = {
  pending: 'fill-panel-2/45 stroke-line',
  skipped: 'fill-panel-2/45 stroke-line',
  done: 'fill-green/[0.025] stroke-green/35',
  active: 'fill-accent/[0.04] stroke-accent/45',
  retry: 'fill-amber/[0.04] stroke-amber/45',
  failed: 'fill-red/[0.035] stroke-red/40',
}

const DOT: Record<AttemptStory['state'], string> = {
  passed: 'fill-green',
  crashed: 'fill-red',
  rejected: 'fill-red',
  open: 'fill-accent pulse-dot',
}

function Section({ box, group, seats, attempts }: { box: Rect; group: GroupScene; seats: number; attempts: AttemptStory[] }) {
  const { state, stage } = group
  const word = STATE_WORD[state]
  const retried = attempts.length > 1
  const y = box.y + 26
  // Rough text widths at these sizes; the long subtitle gives way to the attempt row when both would not fit.
  const meta = panelNoun(stage, seats)
  const used = stage.length * 9.6 + 10 + (meta.length + 8) * 6.4 + (retried ? attempts.length * 10 + 70 : 0) + word.word.length * 7.3
  const subtitle = used + 40 < box.w ? `${meta} ⇄ judge` : meta
  return (
    <g>
      <rect
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={12}
        strokeWidth={1}
        className={`${FRAME[state]} transition-[fill,stroke] duration-300`}
      />
      <text x={box.x + 14} y={y} className="text-[12.5px]">
        <tspan className={`${stage === 'review' ? 'fill-rev' : 'fill-pro'} font-semibold`}>{stage === 'review' ? 'Review' : 'Propose'}</tspan>
        {seats > 0 && (
          <tspan dx={10} className="fill-ink-3 text-[12px]">
            {subtitle}
          </tspan>
        )}
      </text>
      <text x={box.x + box.w - 14} y={y} textAnchor="end" className="text-[12px]">
        {retried &&
          attempts.map((a) => (
            <tspan key={a.n} dx={a.n === 1 ? 0 : 3} className={`${DOT[a.state]} text-[11px]`}>
              ●
            </tspan>
          ))}
        {retried && (
          <tspan dx={6} className="fill-ink-2 font-medium">
            attempt {attempts[attempts.length - 1].n}
          </tspan>
        )}
        <tspan dx={retried ? 10 : 0} className={`${word.cls} font-mono transition-[fill] duration-300`}>
          {word.word}
        </tspan>
      </text>
    </g>
  )
}

/* ------------------------------------------------------------------- edges */

const EDGE_ORDER: Record<Edge['state'], number> = { idle: 0, done: 1, cross: 2, active: 3 }

const EDGE_CLASS: Record<Edge['state'], string> = {
  idle: 'stroke-line-2',
  done: 'stroke-ink-3/45',
  cross: 'stroke-accent/50',
  active: 'stroke-accent/60',
}

function EdgeOverlay({ edge, moving, reduce }: { edge: Edge; moving: boolean; reduce: boolean }) {
  const d = wirePath(edge.wire)
  return (
    <g>
      <motion.path
        d={d}
        fill="none"
        strokeWidth={edge.state === 'active' ? 1.75 : 1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`${EDGE_CLASS[edge.state]} transition-[stroke] duration-300`}
        initial={moving && edge.state === 'active' ? { pathLength: 0 } : false}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.35, ease: EASE }}
      />
      {edge.flow && !reduce && <path d={d} fill="none" strokeWidth={1.75} strokeLinecap="round" className="edge-flow stroke-accent" />}
    </g>
  )
}

function PulseDot({ pulse, wire, onDone }: { pulse: Pulse; wire: Wire; onDone: (id: number) => void }) {
  const { x, y } = wirePoints(wire, 20, pulse.reverse)
  return (
    <motion.circle
      r={4.5}
      className={`${pulse.tone === 'green' ? 'fill-green' : 'fill-accent'} stroke-panel`}
      strokeWidth={1.5}
      initial={{ cx: x[0], cy: y[0], opacity: 0 }}
      animate={{ cx: x, cy: y, opacity: [0, 1, 1, 1, 0] }}
      transition={{ duration: 0.6, ease: 'easeInOut' }}
      onAnimationComplete={() => onDone(pulse.id)}
    />
  )
}

/* ------------------------------------------------------------------- cards */

const CARD_STROKE: Record<NodeState, string> = {
  idle: 'stroke-line-2',
  working: 'stroke-accent',
  done: 'stroke-line-2',
  error: 'stroke-red/70',
  skipped: 'stroke-line-2',
}

function Card({
  box,
  state,
  name,
  title,
  tone,
  moving,
  children,
  chips,
}: {
  box: Rect
  state: NodeState
  name: string
  title: string
  tone?: 'amber'
  moving: boolean
  children?: ReactNode
  chips?: ReactNode
}) {
  const quiet = state === 'idle' || state === 'skipped'
  const stroke = state === 'done' && tone === 'amber' ? 'stroke-amber/70' : CARD_STROKE[state]
  return (
    <g transform={`translate(${box.x} ${box.y})`} opacity={state === 'skipped' ? 0.75 : 1}>
      <title>{title}</title>
      <rect
        width={box.w}
        height={CARD_H}
        rx={8}
        strokeWidth={state === 'working' ? 1.5 : 1}
        strokeDasharray={state === 'skipped' ? '4 4' : undefined}
        className={`fill-panel ${stroke} transition-[stroke] duration-300`}
      />
      <StatusIcon state={state} tone={tone} moving={moving} />
      <text
        x={TEXT_X}
        y={children ? 20 : CARD_H / 2 + 5}
        className={`text-[13.5px] font-semibold transition-[fill] duration-300 ${quiet ? 'fill-ink-3' : 'fill-ink'}`}
      >
        {name}
      </text>
      {children}
      {chips}
    </g>
  )
}

/** The card's second line: a short model, a count, a commit id. */
function Sub({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return (
    <text x={TEXT_X} y={37} className={`fill-ink-3 text-[12px] ${mono ? 'font-mono' : ''}`}>
      {children}
    </text>
  )
}

function StatusIcon({ state, tone, moving }: { state: NodeState; tone?: 'amber'; moving: boolean }) {
  const at = `translate(${ICON.x} ${CARD_H / 2})`
  if (state === 'working') {
    return (
      <g transform={at}>
        <circle r={ICON.r - 1} fill="none" strokeWidth={2} className="stroke-accent/20" />
        <circle r={ICON.r - 1} fill="none" strokeWidth={2} pathLength={100} strokeDasharray="30 70" strokeLinecap="round" className="spin-arc stroke-accent" />
      </g>
    )
  }
  if (state === 'done' || state === 'error') {
    const fill = state === 'error' ? 'fill-red' : tone === 'amber' ? 'fill-amber' : 'fill-green'
    return (
      <g transform={at}>
        <motion.circle
          r={ICON.r}
          className={fill}
          initial={moving ? { scale: 0.5 } : false}
          animate={{ scale: 1 }}
          transition={{ duration: 0.3, ease: EASE }}
        />
        <motion.path
          d={state === 'error' ? 'M-3 -3 L3 3 M3 -3 L-3 3' : 'M-3.6 0.2 L-1.1 2.7 L3.8 -2.3'}
          fill="none"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="stroke-white"
          initial={moving ? { pathLength: 0 } : false}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.3, delay: 0.1, ease: EASE }}
        />
      </g>
    )
  }
  return (
    <circle
      transform={at}
      r={ICON.r - 1}
      fill="none"
      strokeWidth={1.5}
      strokeDasharray={state === 'skipped' ? '2.5 2.5' : undefined}
      className="stroke-ink-3/45"
    />
  )
}

const chipW = (text: string, clock = false) => Math.round(text.length * 6.7 + 14 + (clock ? 13 : 0))

/** A small rounded tag on a card; amber with a clock where an answer timed out, solid while the question is open. */
function Chip({ x, y, text, tone, live, title }: { x: number; y: number; text: string; tone: 'accent' | 'amber'; live?: boolean; title: string }) {
  const clock = tone === 'amber'
  const w = chipW(text, clock)
  // A follow-up that is open right now reads as a solid tag; at rest the tag is a light tint.
  const cls = clock
    ? ['fill-amber/14 stroke-amber/45', 'fill-amber', 'stroke-amber']
    : live
      ? ['fill-accent stroke-accent', 'fill-white', '']
      : ['fill-accent/12 stroke-accent/35', 'fill-accent-2', '']
  return (
    <g transform={`translate(${x} ${y})`}>
      <title>{title}</title>
      <rect width={w} height={18} rx={9} className="fill-panel" />
      <rect width={w} height={18} rx={9} strokeWidth={1} className={cls[0]} />
      {clock && (
        <g transform="translate(12 9)" fill="none" strokeWidth={1.4} strokeLinecap="round" className={cls[2]}>
          <circle r={4.5} />
          <path d="M0 -2.4 V0 L1.8 1.2" />
        </g>
      )}
      <text x={clock ? (w + 13) / 2 : w / 2} y={13} textAnchor="middle" className={`${cls[1]} text-[12px] font-medium`}>
        {text}
      </text>
    </g>
  )
}

function SeatCard({
  node,
  asking,
  selected,
  shake,
  moving,
  onSelect,
}: {
  node: SeatNode
  asking: boolean
  selected: boolean
  shake: Shake | undefined
  moving: boolean
  onSelect: (key: string) => void
}) {
  const { seat, box, state, cross } = node
  const select = () => onSelect(seat.key)
  const onKey = (e: KeyboardEvent) => (e.key === 'Enter' || e.key === ' ') && select()
  const name = seat.judge ? 'judge' : `${seat.stage === 'review' ? 'reviewer' : 'proposer'} ${seat.n}`
  return (
    <g onClick={select} onKeyDown={onKey} role="button" tabIndex={0} aria-label={`${name} ${seat.model}`} className="cursor-pointer outline-none">
      <motion.g
        key={shake?.n ?? 'still'}
        initial={false}
        animate={shake && moving ? { x: [0, -4, 4, -3, 3, 0] } : { x: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        {selected && (
          <rect x={box.x - 3.5} y={box.y - 3.5} width={box.w + 7} height={CARD_H + 7} rx={10.5} fill="none" strokeWidth={2} className="stroke-accent" />
        )}
        <Card
          box={box}
          state={state}
          name={name}
          title={seat.model}
          moving={moving}
          chips={seat.judge ? <JudgeChips box={box} cross={cross} asking={asking} /> : <SeatChipTag box={box} cross={cross} />}
        >
          <Sub mono>{shortModel(seat.model)}</Sub>
        </Card>
      </motion.g>
    </g>
  )
}

/** On a panel seat: the judge asked it a follow-up; amber with a clock when the answer timed out. */
function SeatChipTag({ box, cross }: { box: Rect; cross: SeatNode['cross'] }) {
  if (!cross) return null
  const late = cross.timedOut > 0
  const text = cross.answered > 1 ? `asked ${cross.answered}` : 'asked'
  const title = late ? 'Timed out answering the judge' : `Answered the judge ${cross.answered === 1 ? 'once' : `${cross.answered} times`}`
  return <Chip x={box.w - 8 - chipW(text, late)} y={6} text={text} tone={late ? 'amber' : 'accent'} live={cross.live} title={title} />
}

/** Straddling the judge card's top edge: how many follow-ups it asked, and how many answers timed out. */
function JudgeChips({ box, cross, asking }: { box: Rect; cross: SeatNode['cross']; asking: boolean }) {
  if (!cross && !asking) return null
  const asked = cross ? cross.answered + cross.timedOut : 0
  const late = cross?.timedOut ?? 0
  const main = asking ? 'asking' : `asked ${asked}`
  const x = box.w - 10 - chipW(main)
  return (
    <g>
      <Chip x={x} y={-9} text={main} tone="accent" live={asking} title={`Asked the panel ${asked} follow-up ${asked === 1 ? 'question' : 'questions'}`} />
      {late > 0 && <Chip x={x - 4 - chipW(String(late), true)} y={-9} text={String(late)} tone="amber" title={`${late} timed out`} />}
    </g>
  )
}

/** One dot per session in the batch; amber where the user left feedback. */
function SessionDots({ sessions }: { sessions: { id: string; feedback: boolean }[] }) {
  return (
    <g>
      {sessions.slice(0, 7).map((s, i) => (
        <circle key={s.id} cx={TEXT_X + 3.5 + i * 10} cy={33} r={3.5} className={s.feedback ? 'fill-amber' : 'fill-ink-3/50'}>
          <title>{s.feedback ? `${s.id} · has feedback` : s.id}</title>
        </circle>
      ))}
    </g>
  )
}

function Pop({ on, moving, children }: { on: boolean; moving: boolean; children: ReactNode }) {
  return (
    <motion.g
      key={on ? 'on' : 'off'}
      initial={on && moving ? { scale: 0.88 } : false}
      animate={{ scale: 1 }}
      transition={{ type: 'spring', stiffness: 520, damping: 22 }}
    >
      {children}
    </motion.g>
  )
}
