import { Stage } from '../../kit'
import '../_hone/hone.css'
import './s3.css'

// Final still 3: the review judge cross-examines reviewers 1 and 2; reviewer
// 3 is done. Reviewer 2's answer (abridged from the scripted demo) sits as the
// satellite over the REVIEW frame's lower right corner. The 'running' state
// label is gone: it means nothing on a poster. Type is at least 20 stage px.

// Geometry in stage px, after Hone's own graph: orthogonal wires that share a
// trunk, cards of one height, the judge level with the middle reviewer.
const CARD_H = 60
const PITCH = 66
const G = { x: 16, y: 30, w: 404, h: 242 } // the REVIEW frame
const COL_R = 28 // reviewer column
const R_W = 228
const COL_J = 292
const J_W = 164
const TOP = G.y + 40
const rowY = (i: number) => TOP + i * PITCH
const midY = (i: number) => rowY(i) + CARD_H / 2
const jY = rowY(1)

type Status = 'working' | 'done'

function StatusIcon({ s }: { s: Status }) {
  if (s === 'done')
    return (
      <svg className="s3-ic" width={20} height={20} viewBox="-10 -10 20 20">
        <circle r={9} fill="var(--h-green)" />
        <path d="M-4.2 0.2 L-1.3 3.1 L4.4 -2.7" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  return (
    <svg className="s3-ic" width={20} height={20} viewBox="-10 -10 20 20">
      <circle r={8} fill="none" strokeWidth={2.2} stroke="oklch(0.55 0.17 277 / 0.2)" />
      <circle r={8} fill="none" strokeWidth={2.2} stroke="var(--h-accent)" pathLength={100} strokeDasharray="30 70" strokeLinecap="round" transform="rotate(-30)" />
    </svg>
  )
}

function Node({ x, y, w, name, model, s, tag, tagOnEdge, tone }: { x: number; y: number; w: number; name: string; model?: string; s: Status; tag?: string; tagOnEdge?: boolean; tone?: 'live' }) {
  return (
    <div className="s3-node" data-state={s} style={{ left: x, top: y, width: w, height: CARD_H }}>
      <StatusIcon s={s} />
      <div className="s3-text">
        <div className="s3-name">{name}</div>
        {model && <div className="s3-model">{model}</div>}
      </div>
      {tag && !tagOnEdge && <span className="s3-tag" data-tone={tone}>{tag}</span>}
    </div>
  )
}

// A wire with rounded bends, from (x1,y1) across to a trunk at tx, then to (x2,y2)
function wire(x1: number, y1: number, tx: number, x2: number, y2: number, r = 6) {
  if (y1 === y2) return `M${x1} ${y1} H${x2}`
  const d = y2 > y1 ? 1 : -1
  return `M${x1} ${y1} H${tx - r} Q${tx} ${y1} ${tx} ${y1 + d * r} V${y2 - d * r} Q${tx} ${y2} ${tx + r} ${y2} H${x2}`
}

export default function FinS3() {
  const trunkIn = G.x - 10
  const trunkJ = COL_R + R_W + (COL_J - COL_R - R_W) / 2
  return (
    <Stage width={640} height={360} className="hone s3">
      {() => (
        <>
        <div className="s3-panel" />
        <div className="s3-content">
          <div className="s3-group" style={{ left: G.x, top: G.y, width: G.w, height: G.h }}>
            <div className="s3-ghead">
              <span className="s3-stage">Review</span>
              <span className="s3-gsub">3 reviewers ⇄ judge</span>
            </div>
          </div>

          <svg className="s3-wires" width={640} height={360} viewBox="0 0 640 360">
            {[0, 1, 2].map((i) => (
              <path key={`in${i}`} d={wire(-20, midY(1), trunkIn, COL_R, midY(i))} className="s3-w" />
            ))}
            <path d={wire(COL_R + R_W, midY(2), trunkJ, COL_J, midY(1))} className="s3-w" />
            <path d={wire(COL_R + R_W, midY(0), trunkJ, COL_J, midY(1))} className="s3-w s3-w--cross" />
            <path d={wire(COL_R + R_W, midY(1), trunkJ, COL_J, midY(1))} className="s3-w s3-w--cross" />
            <path d={`M${COL_J + J_W} ${midY(1)} H700`} className="s3-w s3-w--active" />
          </svg>

          <Node x={COL_R} y={rowY(0)} w={R_W} name="reviewer 1" model="DeepSeek V4 Flash" s="working" tag="asked" tone="live" />
          <Node x={COL_R} y={rowY(1)} w={R_W} name="reviewer 2" model="MiniMax M3" s="working" tag="asked" tone="live" />
          <Node x={COL_R} y={rowY(2)} w={R_W} name="reviewer 3" model="MiMo V2.5 Pro" s="done" />
          <Node x={COL_J} y={jY} w={J_W} name="judge" model="GPT-5.4-mini" s="working" tag="asking" tagOnEdge tone="live" />
          <span className="s3-tag" data-edge style={{ left: COL_J + J_W - 10, top: jY - 14 }}>asking</span>
        </div>

          <div className="s3-answer">
            <div className="s3-ahead">
              <span className="s3-who">reviewer 2</span>
              <span className="s3-arrow">→</span>
              <span className="s3-who">judge</span>
            </div>
            <div className="s3-atext">“Both ask for the line to be dropped outright. I withdraw it.”</div>
          </div>
        </>
      )}
    </Stage>
  )
}
