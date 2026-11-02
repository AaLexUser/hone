import { motion, AnimatePresence } from 'motion/react'

const TICKS = 48
const R = 56
const TICK_LEN = 9

export function BatchRing({ filled, total }: { filled: number; total: number }) {
  const fraction = Math.min(filled / total, 1)
  const lit = Math.round(fraction * TICKS)
  const full = filled >= total

  return (
    <div className="relative flex size-[152px] items-center justify-center">
      <svg width={152} height={152} viewBox="0 0 152 152" className="absolute inset-0">
        {Array.from({ length: TICKS }, (_, i) => {
          const angle = (i / TICKS) * Math.PI * 2 - Math.PI / 2
          const x1 = 76 + Math.cos(angle) * R
          const y1 = 76 + Math.sin(angle) * R
          const x2 = 76 + Math.cos(angle) * (R + TICK_LEN)
          const y2 = 76 + Math.sin(angle) * (R + TICK_LEN)
          const on = i < lit
          return (
            <motion.line
              key={i}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              strokeWidth={2.5}
              strokeLinecap="round"
              initial={false}
              animate={{
                stroke: on ? (full ? 'var(--color-green)' : 'var(--color-accent-2)') : 'var(--color-line-2)',
                opacity: on ? 1 : 0.9,
              }}
              transition={{ duration: 0.35, delay: on ? (i % TICKS) * 0.008 : 0 }}
            />
          )
        })}
        {full && (
          <motion.circle
            cx={76}
            cy={76}
            r={R + TICK_LEN / 2}
            fill="none"
            stroke="var(--color-green)"
            strokeWidth={1}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.35, 0.08, 0.35] }}
            transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}
      </svg>
      <div className="flex flex-col items-center">
        <div className="flex items-baseline font-mono">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={filled}
              initial={{ y: 12, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -12, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className={`text-[30px] font-semibold leading-none ${full ? 'text-green' : 'text-ink'}`}
            >
              {filled}
            </motion.span>
          </AnimatePresence>
          <span className="ml-1 text-[15px] text-ink-3">/ {total}</span>
        </div>
        <span className="label mt-1.5">{full ? 'batch ready' : 'collecting'}</span>
      </div>
    </div>
  )
}
