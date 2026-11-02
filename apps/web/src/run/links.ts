import { useCallback, useMemo, useState } from 'react'
import type { ProposedChange, ReviewItem } from '../data'
import { linkEdits } from './derive'

/**
 * Sessions, findings and edits point at each other. Hover previews a link,
 * a click pins it; the focused item lights up everything it touches.
 */

export type Focus = { kind: 'session'; id: string } | { kind: 'finding'; i: number } | { kind: 'edit'; i: number }

export interface Links {
  editFinding: number[]
  findingEdits: number[][]
}

export interface Lit {
  sessions: Set<string>
  findings: Set<number>
  edits: Set<number>
  any: boolean
}

export const sameFocus = (a: Focus | null, b: Focus | null) => JSON.stringify(a) === JSON.stringify(b)

function lit(focus: Focus | null, findings: ReviewItem[], edits: ProposedChange[], links: Links): Lit {
  const sessions = new Set<string>()
  const f = new Set<number>()
  const e = new Set<number>()
  if (focus?.kind === 'session') {
    sessions.add(focus.id)
    findings.forEach((x, i) => x.traceIds.includes(focus.id) && f.add(i))
    edits.forEach((x, i) => x.evidence.includes(focus.id) && e.add(i))
  } else if (focus?.kind === 'finding') {
    f.add(focus.i)
    findings[focus.i]?.traceIds.forEach((id) => sessions.add(id))
    links.findingEdits[focus.i]?.forEach((i) => e.add(i))
  } else if (focus?.kind === 'edit') {
    e.add(focus.i)
    edits[focus.i]?.evidence.forEach((id) => sessions.add(id))
    if (links.editFinding[focus.i] >= 0) f.add(links.editFinding[focus.i])
  }
  return { sessions, findings: f, edits: e, any: focus !== null }
}

export function useLinks(findings: ReviewItem[], edits: ProposedChange[]) {
  const [pinned, setPinned] = useState<Focus | null>(null)
  const [hover, setHover] = useState<Focus | null>(null)
  const links = useMemo<Links>(() => {
    const editFinding = linkEdits(edits, findings)
    const findingEdits = findings.map((_, fi) => editFinding.flatMap((f, ei) => (f === fi ? [ei] : [])))
    return { editFinding, findingEdits }
  }, [edits, findings])
  const pin = useCallback((f: Focus) => setPinned((p) => (sameFocus(p, f) ? null : f)), [])
  // A pin holds until it is clicked again; hover only previews while nothing is pinned.
  const focus = pinned ?? hover
  return { links, lit: lit(focus, findings, edits, links), pinned, pin, hover: setHover }
}

export type LinkApi = ReturnType<typeof useLinks>

/** Scrolls a linked item into view after a click on its link chip. */
export function reveal(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}
