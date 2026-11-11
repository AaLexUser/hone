/**
 * Agent prose as a visitor reads it: the one line a collapsed row shows, the
 * reviewers' mechanism codes in plain words, and messages an older driver cut.
 */

/** The mechanism codes reviewers label findings with, in plain words. The code stays on hover. */
export const MECHANISMS: Record<string, string> = {
  STATE_MISMATCH: 'wrong result',
  DATA_UNAVAILABLE: 'missing data',
  UNSUPPORTED_CLAIM: 'unsupported claim',
  TOOL_LOOP: 'repeated tool calls',
  TOOL_ERROR: 'tool error',
  TOOL_WASTE: 'wasted work',
  INSTRUCTION_CONFLICT: 'conflicting instructions',
  OUTCOME_UNKNOWN: 'outcome unknown',
}

const CODE = /[A-Z]{2,}(?:_[A-Z]+)+/g

/** An absolute path on an agent's machine, two or more folders deep, as in /app/workspace/agents.md. */
export const LOCAL_PATH = /(?<![\w.:/~-])(?:\/[\w@+-]+(?:\.[\w@+-]+)*){2,}\/?/

/** A whole local path, where a name may hold spaces, as in `/home/node/demo/Sales reports`. */
const WHOLE_PATH = /^(?:\/[\w@+.][\w@+.-]*(?: [\w@+.][\w@+.-]*)*){2,}\/?$/

/** A local path's file or folder name, as in agents.md, or null when the text is not a local path. */
export function pathName(text: string): string | null {
  return WHOLE_PATH.test(text) ? text.replace(/\/$/, '').split('/').at(-1)! : null
}

export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** A known code's plain label, or the code itself in lower case words. */
export const mechanism = (code: string) => MECHANISMS[code] ?? code.toLowerCase().replace(/_/g, ' ')

/**
 * A finding that opens with its codes, as in `STATE_MISMATCH (33, high): the weekday column…`,
 * split into a plain label, the prefix it replaces (kept for the tooltip) and the statement.
 */
export function findingLead(statement: string): { label: string; prefix: string; body: string } | null {
  const m = /^((?:[A-Z]{2,}(?:_[A-Z]+)+)[^:\n—]{0,60}?)\s*(?::|—)\s+/.exec(statement)
  if (!m) return null
  const codes = m[1].match(CODE) ?? []
  return {
    label: capitalize(codes.map(mechanism).join(' and ')),
    prefix: m[1],
    body: capitalize(statement.slice(m[0].length)),
  }
}

/** Bold and italic markers and link targets dropped; `code` stays for the inline renderer. */
function plainInline(s: string): string {
  return s
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|[^\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])/g, '$1$2')
}

const ABBREVIATION = /\b(?:e\.g|i\.e|vs|etc|cf|approx|incl)\.$/i

/** A line split after each `.`, `!` or `?` that ends a sentence. */
function sentences(line: string): string[] {
  const out: string[] = []
  let from = 0
  for (const m of line.matchAll(/[.!?]["'”’)\]]*(?=\s|$)/g)) {
    const end = m.index + m[0].length
    if (ABBREVIATION.test(line.slice(from, end))) continue
    out.push(line.slice(from, end).trim())
    from = end
  }
  const rest = line.slice(from).trim()
  if (rest) out.push(rest)
  return out
}

/** Sentences about the agent's own next step, not about the work. */
const PROCESS = /^(?:let me|let's|i'll|i will|i'm going to|now,? (?:let|i)|next,? i)\b/i

const SKIP = /^(?:#{1,6}\s|-{3,}$|\*{3,}$|```|\|)/

/** A reply that only agrees, as in "all three points check out" or "I accept it". */
const ACK = /\b(?:i (?:accept|agree|concede)|checks? out|(?:claim|point|challenger|critique|you|you're) (?:is |are )?(?:accurate|right|correct))\b/i

/** What an agreeing reply says it adds, as in "I accept it, with one scope correction." */
const ADDS = /\bwith (?:one|a|an|two|three|some) ([a-z]+(?: [a-z]+)?)[.!?]?$/i

/** The message's lines a collapsed row may show, as plain text without list markers. */
function bodyLines(text: string): string[] {
  const lines = text.split('\n').map((l) => l.trim())
  const heading = lines.findIndex((l) => /^#{1,6}\s/.test(l))
  const preamble = heading > 0 && sentences(plainInline(lines.slice(0, heading).join(' '))).some((s) => PROCESS.test(s))
  const out: string[] = []
  for (const raw of lines.slice(preamble ? heading : 0)) {
    if (!raw || SKIP.test(raw)) continue
    const line = plainInline(raw).replace(/^(?:(?:[-*+]|\d+[.)])\s+)+/, '')
    const label = /:$/.test(line) || (/^\*\*[^*]+\*\*$/.test(raw) && !/[.!?]["'”’)\]]*$/.test(line))
    if (line && !label) out.push(line)
  }
  return out
}

/**
 * The first real sentence of an agent message, for its collapsed row: past a
 * process preamble ("I have enough evidence. Let me compile the report."),
 * headings, rules and label lines such as **Short answers** or "Direct answers:",
 * with list markers and bold or italic markers dropped. A bare agreement such as
 * "I accept it, with one scope correction." gives way to the line it announces
 * ("Scope correction: …"), or else to the next sentence.
 */
export function headline(text: string): string {
  const lines = bodyLines(text)
  const said = lines.flatMap((l) => sentences(l).filter((s) => !PROCESS.test(s)))
  const [first, next] = said
  if (first && next && ACK.test(first) && !first.includes(':')) {
    const adds = ADDS.exec(first)?.[1].toLowerCase()
    const announced = adds && lines.find((l) => /^[^:]{1,40}:\s/.test(l) && l.slice(0, l.indexOf(':')).toLowerCase().includes(adds))
    return announced ? sentences(announced)[0] : next
  }
  return first ?? plainInline(text.split('\n').map((l) => l.trim()).find((l) => l && !SKIP.test(l)) ?? '')
}

/** The length the driver once cut every agent message to. */
export const OLD_MESSAGE_CAP = 4000

/**
 * A message the driver cut at {@link OLD_MESSAGE_CAP} characters, often mid word,
 * ends at its last full sentence or line instead, with an ellipsis to show more was written.
 */
export function uncut(text: string): string {
  if (text.length !== OLD_MESSAGE_CAP || /[.!?…]\s*$/.test(text)) return text
  const last = [...text.matchAll(/[.!?]["'”’)\]]*(?=\s)|\n/g)].at(-1)
  return last ? `${text.slice(0, last.index + last[0].length).trimEnd()}\n\n…` : text
}
