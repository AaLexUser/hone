import type { Stage } from '../events'
import type { Seat } from '../model'
import type { LaneGroup } from '../derive'
import { shortModel } from '../derive'

/**
 * Geometry of the MAJICS graph as cards, computed from the roster alone:
 *
 *   Traces → [ K reviewers → judge ] → Report → [ M proposers → judge ] → Verify → Commit
 *
 * Units are CSS pixels at a viewBox at least 1360 wide, which is the graph's
 * width on a 1440 px screen, so text sizes here are what that screen shows.
 */

export interface Pt {
  x: number
  y: number
}

/** x, y is the top-left corner. */
export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface Spot {
  seat: Seat
  box: Rect
}

export interface GroupLayout {
  stage: Stage
  box: Rect
  panel: Spot[]
  judge: Spot | null
}

export interface GraphLayout {
  w: number
  h: number
  cy: number
  traces: Rect
  report: Rect
  verify: Rect
  commit: Rect
  groups: [GroupLayout, GroupLayout]
}

/** An orthogonal edge: across from `a`, along a vertical trunk at `xm`, across into `b`. */
export interface Wire {
  a: Pt
  b: Pt
  xm: number
}

export const CARD_H = 48
const PITCH = 58
const MIN_W = 1360
const MONO_CH = 7.25
/** Room left of the text for the status icon, and right of it. */
export const TEXT_X = 32
const PAD_R = 14
const SECTION = { padX: 12, head: 44, padB: 14 }
const OUTER = 4
const INNER_GAP = 36
const TAIL_GAP = 36

const fit = (model: string, min: number) => Math.max(min, Math.ceil(shortModel(model).length * MONO_CH + TEXT_X + PAD_R))

export const left = (r: Rect): Pt => ({ x: r.x, y: r.y + r.h / 2 })
export const right = (r: Rect): Pt => ({ x: r.x + r.w, y: r.y + r.h / 2 })

function rows(n: number, cy: number): number[] {
  return Array.from({ length: n }, (_, i) => cy + (i - (n - 1) / 2) * PITCH)
}

export function graphLayout([review, propose]: LaneGroup[]): GraphLayout {
  const panelSeats = [...review.panel, ...propose.panel]
  const judges = [review.judge, propose.judge].filter((s): s is Seat => !!s)
  const panelW = Math.max(184, ...panelSeats.map((s) => fit(s.model, 0)))
  const judgeW = Math.max(132, ...judges.map((s) => fit(s.model, 0)))
  const io = { traces: 96, report: 108, verify: 96, commit: 104 }
  const fixed = io.traces + io.report + io.verify + io.commit + 2 * (panelW + INNER_GAP + judgeW) + TAIL_GAP
  // Four gaps border a stage box; they share what is left, so boxes never crowd their neighbours.
  const minGap = 2 * SECTION.padX + 34
  const w = Math.max(MIN_W, fixed + 4 * minGap + 2 * OUTER)
  const gap = (w - 2 * OUTER - fixed) / 4

  const tallest = Math.max(review.panel.length, propose.panel.length, 1)
  const panelH = (tallest - 1) * PITCH + CARD_H
  const top = OUTER
  const cy = top + SECTION.head + panelH / 2
  const card = (x: number, wd: number, y = cy): Rect => ({ x, y: y - CARD_H / 2, w: wd, h: CARD_H })

  let x = OUTER
  const traces = card(x, io.traces)
  x += io.traces + gap
  const group = (g: LaneGroup): GroupLayout => {
    const panelX = x
    const judgeX = panelX + panelW + INNER_GAP
    const n = Math.max(g.panel.length, 1)
    const h = (n - 1) * PITCH + CARD_H
    const box: Rect = {
      x: panelX - SECTION.padX,
      y: cy - h / 2 - SECTION.head,
      w: panelW + INNER_GAP + judgeW + 2 * SECTION.padX,
      h: h + SECTION.head + SECTION.padB,
    }
    const ys = rows(g.panel.length, cy)
    x = judgeX + judgeW + gap
    return {
      stage: g.stage,
      box,
      panel: g.panel.map((seat, i) => ({ seat, box: card(panelX, panelW, ys[i]) })),
      judge: g.judge ? { seat: g.judge, box: card(judgeX, judgeW) } : null,
    }
  }
  const reviewG = group(review)
  const report = card(x, io.report)
  x += io.report + gap
  const proposeG = group(propose)
  const verify = card(x, io.verify)
  const commit = card(x + io.verify + TAIL_GAP, io.commit)
  const h = Math.max(reviewG.box.y + reviewG.box.h, proposeG.box.y + proposeG.box.h) + OUTER
  return { w, h, cy, traces, report, verify, commit, groups: [reviewG, proposeG] }
}

const CORNER = 8

export function wirePath({ a, b, xm }: Wire): string {
  if (Math.abs(b.y - a.y) < 1) return `M ${a.x} ${a.y} H ${b.x}`
  const s = b.y > a.y ? 1 : -1
  const r = Math.min(CORNER, Math.abs(b.y - a.y) / 2, Math.abs(xm - a.x), Math.abs(b.x - xm))
  return [
    `M ${a.x} ${a.y}`,
    `H ${xm - r}`,
    `Q ${xm} ${a.y} ${xm} ${a.y + s * r}`,
    `V ${b.y - s * r}`,
    `Q ${xm} ${b.y} ${xm + r} ${b.y}`,
    `H ${b.x}`,
  ].join(' ')
}

/** Evenly spaced points along the wire, for a pulse that travels it as motion keyframes. */
export function wirePoints({ a, b, xm }: Wire, n = 20, reverse = false): { x: number[]; y: number[] } {
  const corners = [a, { x: xm, y: a.y }, { x: xm, y: b.y }, b]
  const lens = corners.slice(1).map((p, i) => Math.abs(p.x - corners[i].x) + Math.abs(p.y - corners[i].y))
  const total = lens.reduce((s, l) => s + l, 0) || 1
  const x: number[] = []
  const y: number[] = []
  for (let i = 0; i <= n; i++) {
    let d = ((reverse ? n - i : i) / n) * total
    let k = 0
    while (k < lens.length - 1 && d > lens[k]) d -= lens[k++]
    const t = lens[k] ? d / lens[k] : 0
    x.push(corners[k].x + (corners[k + 1].x - corners[k].x) * t)
    y.push(corners[k].y + (corners[k + 1].y - corners[k].y) * t)
  }
  return { x, y }
}
