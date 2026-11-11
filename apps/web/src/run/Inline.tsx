import type { ReactNode } from 'react'
import { LOCAL_PATH, MECHANISMS, capitalize, mechanism, pathName } from './prose'

const TOKEN = new RegExp(
  [
    /`([^`\n]+)`/.source,
    /\*\*(.+?)\*\*/.source,
    /(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])/.source,
    `\\b(${Object.keys(MECHANISMS).join('|')})\\b`,
    /\b(review|propose)-(\d+)\b/.source,
    /\b(promptVersion)\b/.source,
    `(${LOCAL_PATH.source})`,
  ].join('|'),
  'g',
)

/** A plain word for a pipeline term, with the term itself on hover. */
function Term({ code, children }: { code: string; children: ReactNode }) {
  return (
    <abbr title={code} className="no-underline">
      {children}
    </abbr>
  )
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN)) {
    out.push(text.slice(last, m.index))
    last = m.index + m[0].length
    const k = m.index
    const atStart = /(?:^|[.!?:\n(]\s*)$/.test(text.slice(0, m.index))
    const label = (code: string) => (atStart ? capitalize(mechanism(code)) : mechanism(code))
    const [, code, bold, italic, known, seatStage, seatN, field, path] = m
    if (code !== undefined)
      out.push(
        code in MECHANISMS ? (
          <Term key={k} code={code}>
            {label(code)}
          </Term>
        ) : (
          <code key={k} title={pathName(code) ? code : undefined} className="rounded-[4px] bg-ink/6 px-1 font-mono text-[0.92em] text-ink">
            {pathName(code) ?? code}
          </code>
        ),
      )
    else if (bold !== undefined) out.push(<strong key={k} className="font-semibold text-ink">{inline(bold)}</strong>)
    else if (italic !== undefined) out.push(<em key={k}>{inline(italic)}</em>)
    else if (known !== undefined)
      out.push(
        <Term key={k} code={known}>
          {label(known)}
        </Term>,
      )
    else if (seatStage !== undefined)
      out.push(
        <Term key={k} code={m[0]}>
          {seatStage === 'review' ? 'reviewer' : 'proposer'} {seatN}
        </Term>,
      )
    else if (field !== undefined)
      out.push(
        <Term key={k} code={field}>
          prompt version
        </Term>,
      )
    else if (path !== undefined)
      out.push(
        <Term key={k} code={path}>
          {pathName(path) ?? path}
        </Term>,
      )
  }
  out.push(text.slice(last))
  return out
}

/**
 * Agent prose on one line: `code`, **bold** and *italic*, with reviewer mechanism
 * codes, seat names and field names in plain words, local paths by their file or
 * folder name, and the original on hover.
 */
export function Inline({ text }: { text: string }) {
  return <>{inline(text)}</>
}

type Block =
  | { type: 'heading' | 'para'; lines: string[] }
  | { type: 'list'; items: { depth: number; marker: string; text: string }[] }
  | { type: 'pre'; lines: string[] }
  | { type: 'rule' }

const ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/

function blocks(text: string): Block[] {
  const out: Block[] = []
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const top = out.at(-1)
    if (/^\s*```/.test(line)) {
      const body: string[] = []
      while (++i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i])
      out.push({ type: 'pre', lines: body })
    } else if (/^\s*\|/.test(line)) {
      if (top?.type === 'pre' && /^\s*\|/.test(lines[i - 1])) top.lines.push(line)
      else out.push({ type: 'pre', lines: [line] })
    } else if (/^\s*(?:-{3,}|\*{3,})\s*$/.test(line)) out.push({ type: 'rule' })
    else if (/^\s*#{1,6}\s/.test(line)) out.push({ type: 'heading', lines: [line.replace(/^\s*#+\s*/, '')] })
    else if (ITEM.test(line)) {
      const [, indent, marker, body] = ITEM.exec(line)!
      const item = { depth: Math.floor(indent.length / 2), marker: /\d/.test(marker) ? marker : '•', text: body }
      if (top?.type === 'list') top.items.push(item)
      else out.push({ type: 'list', items: [item] })
    } else if (!line.trim()) continue
    else if (top?.type === 'list' && /^\s+/.test(line) && lines[i - 1]?.trim()) top.items[top.items.length - 1].text += ` ${line.trim()}`
    else if (top?.type === 'para' && lines[i - 1]?.trim()) top.lines.push(line)
    else out.push({ type: 'para', lines: [line] })
  }
  return out
}

/** An agent message rendered as the markdown it was written in: headings, lists, rules, code and tables. */
export function Prose({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2 text-body break-words text-ink-2">
      {blocks(text).map((b, i) => {
        switch (b.type) {
          case 'heading':
            return (
              <p key={i} className="pt-1 font-semibold text-ink">
                <Inline text={b.lines[0]} />
              </p>
            )
          case 'para':
            return (
              <p key={i}>
                {b.lines.map((l, j) => (
                  <span key={j}>
                    {j > 0 && <br />}
                    <Inline text={l} />
                  </span>
                ))}
              </p>
            )
          case 'list':
            return (
              <ul key={i} className="flex flex-col gap-1">
                {b.items.map((it, j) => (
                  <li key={j} className="flex gap-2" style={{ paddingLeft: `${it.depth * 16}px` }}>
                    <span className="shrink-0 text-ink-3 tabular-nums">{it.marker}</span>
                    <span className="min-w-0">
                      <Inline text={it.text} />
                    </span>
                  </li>
                ))}
              </ul>
            )
          case 'pre':
            return (
              <pre key={i} className="overflow-x-auto rounded-md bg-ink/5 px-2 py-1.5 font-mono text-meta text-ink">
                {b.lines.join('\n')}
              </pre>
            )
          case 'rule':
            return <hr key={i} className="border-line" />
        }
      })}
    </div>
  )
}
