import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ReviewItem } from '../data'

/** Card shell shared by the run page's right-hand regions. */
export function Panel({ icon, title, count, action, children }: { icon: ReactNode; title: string; count?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card overflow-hidden">
      <header className="flex h-12 items-center gap-2.5 border-b border-line px-4">
        <span className="text-ink-3">{icon}</span>
        <h2 className="text-emph font-semibold text-ink">{title}</h2>
        {count !== undefined && <span className="text-body text-ink-3 tabular-nums">{count}</span>}
        <span className="ml-auto flex items-center gap-2">{action}</span>
      </header>
      {children}
    </section>
  )
}

const BARS: Record<ReviewItem['confidence'], number> = { high: 3, medium: 2, low: 1 }

/** Confidence as three rising bars. */
export function Confidence({ level }: { level: ReviewItem['confidence'] }) {
  const n = BARS[level]
  return (
    <span className="flex items-end gap-[2px]" title={`${level} confidence`} aria-label={`${level} confidence`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={`w-[3px] rounded-[1px] ${i <= n ? 'bg-ink-2' : 'bg-line-2'}`} style={{ height: 4 + i * 3 }} />
      ))}
    </span>
  )
}

export function SessionChips({ ids, lit }: { ids: string[]; lit?: Set<string> }) {
  return (
    <>
      {ids.map((id) => (
        <Link
          key={id}
          to={`/traces/${id}`}
          className={`rounded-[5px] px-1.5 py-px font-mono text-meta transition-colors ${
            lit?.has(id) ? 'bg-accent/15 text-accent-2' : 'text-ink-3 ring-1 ring-line ring-inset hover:text-ink-2'
          }`}
        >
          {id}
        </Link>
      ))}
    </>
  )
}

/** A clickable F1 / E2 reference to a linked item. */
export function RefChip({ label, on, onClick, title }: { label: string; on: boolean; onClick: () => void; title: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`rounded-[5px] px-1.5 py-px font-mono text-meta font-semibold transition-colors ${
        on ? 'bg-accent text-white' : 'bg-accent/10 text-accent-2 hover:bg-accent/20'
      }`}
    >
      {label}
    </button>
  )
}

export function DiffLine({ sign, text, a, b }: { sign: '+' | '−' | ' '; text: string; a?: number | null; b?: number | null }) {
  const tone = sign === '+' ? 'bg-green/10 text-ink' : sign === '−' ? 'bg-red/10 text-ink-2' : 'text-ink-3'
  const numbered = a !== undefined || b !== undefined
  return (
    <div className={`flex gap-2 pr-3 ${numbered ? '' : 'pl-3'} ${tone}`}>
      {numbered && (
        <span className="w-14 shrink-0 select-none pl-2 text-right text-ink-3/70 tabular-nums">
          {b ?? a ?? ''}
        </span>
      )}
      <span className={`w-3 shrink-0 select-none ${sign === '+' ? 'text-green' : sign === '−' ? 'text-red' : ''}`}>{sign}</span>
      <span className="min-w-0 break-words whitespace-pre-wrap">{text || ' '}</span>
    </div>
  )
}

/** Placeholder lines; they shimmer only while the content is moments away (`live`). */
export function Skeleton({ live = false }: { live?: boolean }) {
  return (
    <div className="flex flex-col gap-2.5 px-4 py-4" aria-hidden>
      {[0, 1].map((i) => (
        <span key={i} className={`h-2.5 rounded ${live ? 'shimmer' : 'bg-panel-2'}`} style={{ width: `${88 - i * 22}%` }} />
      ))}
    </div>
  )
}
