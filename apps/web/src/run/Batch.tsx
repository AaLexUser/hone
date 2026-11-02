import { Link } from 'react-router-dom'
import { Layers, MessageSquare } from 'lucide-react'
import type { Trace } from '../data'
import type { LinkApi } from './links'

/** The frozen batch: each session's opening request and, where the user left it, their feedback. */
export function Batch({ ids, traces, base, links }: { ids: string[]; traces: Trace[]; base: string; links: LinkApi }) {
  const { lit, hover } = links
  return (
    <section className="card overflow-hidden">
      <header className="flex h-12 items-center gap-2.5 border-b border-line px-4">
        <Layers size={16} className="text-ink-3" />
        <h2 className="text-emph font-semibold text-ink">Batch</h2>
        <span className="text-body text-ink-3 tabular-nums">{ids.length}</span>
        <span className="ml-auto font-mono text-meta text-ink-3" title="AGENTS.md version the batch ran on">
          {base}
        </span>
      </header>
      <ol>
        {ids.map((id) => {
          const t = traces.find((x) => x.id === id)
          const on = lit.sessions.has(id)
          return (
            <li key={id}>
              <Link
                to={`/traces/${id}`}
                onMouseEnter={() => hover({ kind: 'session', id })}
                onMouseLeave={() => hover(null)}
                className={`block border-l-2 px-4 py-2.5 transition-[opacity,background-color] duration-150 hover:bg-panel-2 ${
                  on ? 'border-accent bg-accent/6' : 'border-transparent'
                } ${lit.any && !on ? 'opacity-50' : ''}`}
              >
                <div className="flex items-baseline gap-3">
                  <span className="shrink-0 font-mono text-meta text-ink-3">{id}</span>
                  <span className="truncate text-body text-ink">{t?.firstLine}</span>
                </div>
                {t?.feedback && (
                  <div className="mt-1 flex gap-2 text-body text-ink-2">
                    <MessageSquare size={13} className="mt-[3px] shrink-0 text-amber" aria-label="User feedback" />
                    <span className="line-clamp-2">{t.feedback}</span>
                  </div>
                )}
              </Link>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
