import { ArrowUpRight, CircleHelp, ScrollText } from 'lucide-react'
import type { Review } from '../data'
import { Inline } from './Inline'
import { findingLead } from './prose'
import { Confidence, Panel, RefChip, SessionChips, Skeleton } from './bits'
import { reveal, sameFocus } from './links'
import type { LinkApi } from './links'
import { url } from '../lib/url'

/** The review report, rendered natively: summary, then findings with the edits they led to. */
export function Findings({
  runId,
  review,
  writing,
  links,
}: {
  runId: string
  review: Review | null
  /** The review judge is writing the report right now. */
  writing: boolean
  links: LinkApi
}) {
  const { lit, pinned, pin, hover } = links
  return (
    <Panel
      icon={<ScrollText size={16} />}
      title="Review report"
      count={review ? review.findings.length : undefined}
      action={
        review && (
          <a
            href={url(`/api/runs/${runId}/report`)}
            target="_blank"
            rel="noreferrer"
            className="btn-ghost flex items-center gap-1 rounded-md px-2 py-0.5 text-meta text-ink-2 hover:text-ink"
          >
            open <ArrowUpRight size={12} />
          </a>
        )
      }
    >
      {!review ? (
        writing && <Skeleton live />
      ) : (
        <div className="pb-2">
          {review.summary && (
            <p className="border-b border-line px-4 py-3 text-body text-ink-2">
              <Inline text={review.summary} />
            </p>
          )}
          <ol>
            {review.findings.map((f, i) => {
              const on = lit.findings.has(i)
              const lead = findingLead(f.statement)
              const edits = links.links.findingEdits[i] ?? []
              return (
                <li
                  key={i}
                  id={`finding-${i}`}
                  onMouseEnter={() => hover({ kind: 'finding', i })}
                  onMouseLeave={() => hover(null)}
                  className={`border-l-2 px-4 py-3 transition-[opacity,background-color] duration-150 ${
                    on ? 'border-accent bg-accent/6' : 'border-transparent'
                  } ${lit.any && !on ? 'opacity-50' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <RefChip
                      label={`F${i + 1}`}
                      on={sameFocus(pinned, { kind: 'finding', i })}
                      onClick={() => pin({ kind: 'finding', i })}
                      title="Pin this finding"
                    />
                    <Confidence level={f.confidence} />
                    {lead && (
                      <abbr title={lead.prefix} className="text-meta font-medium text-ink-2 no-underline">
                        {lead.label}
                      </abbr>
                    )}
                    {edits.length > 0 && (
                      <span className="ml-auto flex items-center gap-1 text-meta text-ink-3">
                        →
                        {edits.map((e) => (
                          <RefChip
                            key={e}
                            label={`E${e + 1}`}
                            on={sameFocus(pinned, { kind: 'edit', i: e })}
                            onClick={() => {
                              pin({ kind: 'edit', i: e })
                              reveal(`edit-${e}`)
                            }}
                            title={`Edit ${e + 1} acts on this finding`}
                          />
                        ))}
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-body text-ink">
                    <Inline text={lead?.body ?? f.statement} />
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <SessionChips ids={f.traceIds} lit={lit.sessions} />
                  </div>
                </li>
              )
            })}
          </ol>
          <More review={review} />
        </div>
      )}
    </Panel>
  )
}

function More({ review }: { review: Review }) {
  const n = review.hypotheses.length + review.unresolved.length
  if (!n) return null
  return (
    <details className="group px-4 pt-1">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-meta text-ink-3 hover:text-ink-2">
        <CircleHelp size={13} />
        {n} open {n === 1 ? 'question' : 'questions'}
      </summary>
      <ul className="mt-2 flex flex-col gap-2 pb-2 text-body text-ink-2">
        {review.hypotheses.map((h, i) => (
          <li key={`h${i}`} className="flex gap-2">
            <span className="mt-1.5">
              <Confidence level={h.confidence} />
            </span>
            <Inline text={h.statement} />
          </li>
        ))}
        {review.unresolved.map((u, i) => (
          <li key={`u${i}`} className="flex gap-2">
            <span className="text-ink-3">?</span>
            <Inline text={u} />
          </li>
        ))}
      </ul>
    </details>
  )
}
