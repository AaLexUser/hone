import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { ChevronRight, Download, MessageSquare, Wrench } from 'lucide-react'
import { useStore, relTime } from '../store'
import type { Trace, ConversationTurn } from '../data'
import { Badge } from '../components/ui'

export function TracePage() {
  const { id } = useParams()
  const { state } = useStore()
  const fallback = state.traces.find((t) => t.id === id) ?? state.traces[0]
  const [detail, setDetail] = useState<{
    trace: Trace
    conversation: ConversationTurn[]
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/traces/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => !cancelled && setDetail({ trace: d, conversation: d.conversation }))
      .catch(() => !cancelled && setDetail(null))
    return () => {
      cancelled = true
    }
  }, [id])

  const trace = detail?.trace ?? fallback
  if (!trace) {
    return <div className="px-5 py-10 text-center text-[12.5px] text-ink-3">Trace not found.</div>
  }
  const conversation = detail?.conversation ?? []

  return (
    <div>
      <nav className="mb-5 flex items-center gap-1.5 text-[12.5px] text-ink-3">
        <Link to="/" className="hover:text-ink-2">
          Dashboard
        </Link>
        <ChevronRight size={13} />
        <span className="font-mono text-[12px] text-ink-2">{trace.id}</span>
      </nav>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1fr_290px]">
        <motion.div
          initial="hidden"
          animate="show"
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
          className="flex flex-col gap-3"
        >
          {trace.feedback && (
            <motion.div
              variants={rise}
              className="flex items-start gap-2.5 rounded-lg border border-amber/30 bg-amber/6 px-4 py-3"
            >
              <MessageSquare size={14} className="mt-0.5 shrink-0 text-amber" />
              <div>
                <div className="label text-amber/80">User feedback</div>
                <div className="mt-1 text-[13px] text-amber/95">{trace.feedback}</div>
              </div>
            </motion.div>
          )}

          {conversation.map((turn, i) =>
            turn.role === 'tool' ? (
              <ToolRow key={i} name={turn.tool!.name} args={turn.tool!.args} result={turn.tool!.result} />
            ) : (
              <motion.div key={i} variants={rise} className="card px-4 py-3">
                <div className={`label ${turn.role === 'user' ? 'text-accent-2' : ''}`}>{turn.role}</div>
                <p className="mt-1.5 max-w-[560px] text-[13.5px] leading-relaxed text-ink">{turn.text}</p>
              </motion.div>
            ),
          )}
          {conversation.length === 0 && (
            <div className="card px-4 py-3 text-[12.5px] text-ink-3">Loading conversation…</div>
          )}
        </motion.div>

        <motion.aside
          initial={{ opacity: 0, x: 12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          className="card static px-4 py-4 lg:sticky lg:top-[76px]"
        >
          <div className="label">Session</div>
          <div className="mt-1 font-mono text-[12px]">{trace.id}</div>
          <dl className="mt-4 flex flex-col gap-3 text-[12.5px]">
            <MetaRow k="Stored">{relTime(trace.receivedAt)}</MetaRow>
            <MetaRow k="Turns">{trace.turns}</MetaRow>
            <MetaRow k="Status">
              <Badge kind={trace.status} />
            </MetaRow>
            <MetaRow k="AGENTS.md">
              <Link to="/versions" className="font-mono text-[11.5px] text-accent-2 hover:underline">
                {trace.versionId}
              </Link>
            </MetaRow>
          </dl>
          <a
            href={`/api/traces/${trace.id}/jsonl`}
            download={`${trace.id}.jsonl`}
            className="btn-ghost mt-5 flex w-full items-center justify-center gap-2 rounded-md px-3 py-1.5 text-[12px] text-ink-2"
          >
            <Download size={13} />
            Download raw JSONL
          </a>
        </motion.aside>
      </div>
    </div>
  )
}

const rise = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 340, damping: 30 } },
}

function MetaRow({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-ink-3">{k}</dt>
      <dd className="text-ink-2">{children}</dd>
    </div>
  )
}

function ToolRow({ name, args, result }: { name: string; args: string; result: string }) {
  const [open, setOpen] = useState(false)
  return (
    <motion.div variants={rise} className="card overflow-hidden">
      <button onClick={() => setOpen(!open)} className="hover-row flex w-full items-center gap-2.5 px-4 py-2.5 text-left">
        <Wrench size={12} className="shrink-0 text-ink-3" />
        <span className="font-mono text-[12px] text-ink-2">{name}</span>
        <span className="truncate font-mono text-[11.5px] text-ink-3">{args}</span>
        <motion.span animate={{ rotate: open ? 90 : 0 }} className="ml-auto text-ink-3">
          <ChevronRight size={13} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="border-t border-line bg-panel-2 px-4 py-3 font-mono text-[11.5px] leading-relaxed text-ink-2">
              → {result}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
