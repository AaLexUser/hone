import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { animate } from 'motion/react'

const badgeStyles: Record<string, string> = {
  new: 'text-accent-2 bg-accent/12 border-accent/30',
  analyzed: 'text-ink-2 bg-ink/4 border-line-2',
  running: 'text-accent-2 bg-accent/12 border-accent/30',
  validating: 'text-amber bg-amber/10 border-amber/30',
  succeeded: 'text-green bg-green/10 border-green/25',
  failed: 'text-red bg-red/10 border-red/30',
  'no-changes': 'text-ink-2 bg-ink/4 border-line-2',
  current: 'text-green bg-green/10 border-green/25',
}

const badgeLabels: Record<string, string> = { 'no-changes': 'no changes' }

export function Badge({ kind, children }: { kind: string; children?: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[5px] border px-1.5 py-px text-[11px] font-medium ${badgeStyles[kind] ?? badgeStyles.analyzed}`}
    >
      {(kind === 'running' || kind === 'validating') && (
        <span className="pulse-dot size-1.5 rounded-full bg-current" />
      )}
      {children ?? badgeLabels[kind] ?? kind}
    </span>
  )
}

export function StatCard({
  label,
  extra,
  to,
  children,
}: {
  label: string
  extra?: React.ReactNode
  /** Turns the card into a link — used for "Last run". */
  to?: string
  children: React.ReactNode
}) {
  const body = (
    <>
      <div className="label">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-2">{children}</div>
      {extra && <div className="absolute right-3 bottom-3 opacity-80">{extra}</div>}
    </>
  )
  const cls = 'card relative block overflow-hidden px-4 py-3.5'
  return to ? (
    <Link to={to} className={`${cls} hover-row transition-colors`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

export function CountUp({ value, className }: { value: number; className?: string }) {
  const [display, setDisplay] = useState(value)
  const prev = useRef(value)
  useEffect(() => {
    const controls = animate(prev.current, value, {
      duration: 0.7,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(Math.round(v)),
    })
    prev.current = value
    return () => controls.stop()
  }, [value])
  return <span className={className}>{display}</span>
}

export function Sparkline({ points, className }: { points: number[]; className?: string }) {
  const w = 96
  const h = 28
  const max = Math.max(...points, 1)
  const step = w / (points.length - 1)
  const d = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(h - 3 - (p / max) * (h - 8)).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={w} height={h} className={className}>
      <path d={d} fill="none" stroke="var(--color-accent-2)" strokeWidth="1.5" opacity="0.9" />
      <path
        d={`${d} L${w},${h} L0,${h} Z`}
        fill="url(#spark-fill)"
        stroke="none"
        opacity="0.35"
      />
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  )
}
