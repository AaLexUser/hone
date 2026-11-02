export type DotTone = 'idle' | 'live' | 'done' | 'failed'

const TONE: Record<DotTone, string> = {
  idle: 'bg-ink-3/60',
  live: 'bg-accent pulse-dot',
  done: 'bg-green',
  failed: 'bg-red',
}

/** Status is a small dot, never a filled badge. */
export function StatusDot({ tone, className = '' }: { tone: DotTone; className?: string }) {
  return <span aria-hidden className={`inline-block size-2 shrink-0 rounded-full ${TONE[tone]} ${className}`} />
}
