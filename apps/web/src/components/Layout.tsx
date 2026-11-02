import { NavLink, Link, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { Moon, Sun } from 'lucide-react'
import { useStore } from '../store'
import { useTheme } from '../lib/theme'
import { pageWidth } from '../lib/pageWidth'

const tabs = [
  { to: '/', label: 'Dashboard' },
  { to: '/runs', label: 'Runs' },
  { to: '/versions', label: 'Versions' },
]

/** Three document lines; the middle one is honed to a point. */
export function Mark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden>
      <defs>
        <linearGradient id="mark-bg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7280ee" />
          <stop offset="100%" stopColor="#4653c9" />
        </linearGradient>
      </defs>
      <rect width="20" height="20" rx="5.5" fill="url(#mark-bg)" />
      <rect x="4.6" y="5.3" width="6.5" height="1.8" rx="0.9" fill="#fff" opacity="0.55" />
      <rect x="4.6" y="9.1" width="7.2" height="1.8" rx="0.9" fill="#fff" />
      <path d="M11 9.1 L15.6 10 L11 10.9 Z" fill="#fff" />
      <rect x="4.6" y="12.9" width="4.6" height="1.8" rx="0.9" fill="#fff" opacity="0.55" />
    </svg>
  )
}

export function Header() {
  const { state } = useStore()
  const runActive = state.run && state.run.status !== 'succeeded'
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
      <div className={`mx-auto flex h-12 items-center ${pageWidth(pathname)} gap-3 px-4 sm:gap-5 sm:px-6`}>
        <Link to="/" className="flex items-center gap-2.5">
          <Mark size={20} />
          <span className="text-[13.5px] font-semibold tracking-tight">Hone</span>
          <span className="hidden rounded-[4px] border border-line-2 px-1.5 py-px font-mono text-[10px] font-medium text-ink-3 sm:block">
            AGENTS.md
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {tabs.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.to === '/'} className="relative rounded-md px-2.5 py-1.5 text-[12.5px]">
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-md bg-ink/8"
                      transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                    />
                  )}
                  <span className={`relative ${isActive ? 'text-ink' : 'text-ink-2 hover:text-ink'}`}>{t.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <AnimatePresence>
            {runActive && (
              <motion.div initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }}>
                <Link
                  to={`/runs/${state.run!.id}`}
                  className="flex items-center gap-2 rounded-md border border-accent/35 bg-accent/10 px-2.5 py-1 text-[12px] text-accent-2"
                >
                  <span className="pulse-dot size-1.5 rounded-full bg-accent-2" />
                  <span className="hidden sm:inline">optimization running</span>
                  <span className="sm:hidden">running</span>
                </Link>
              </motion.div>
            )}
          </AnimatePresence>
          <button
            onClick={toggleTheme}
            className="btn-ghost grid size-7 place-items-center rounded-md text-ink-2 hover:text-ink"
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <Link
            to="/versions"
            className="btn-ghost flex items-center gap-2 rounded-md px-2.5 py-1 font-mono text-[11.5px] text-ink-2"
            title="Current AGENTS.md version (git HEAD)"
          >
            <span className="size-1.5 rounded-full bg-green" />
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={state.currentId}
                initial={{ y: 8, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: -8, opacity: 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 34 }}
              >
                {state.currentId}
              </motion.span>
            </AnimatePresence>
            {state.currentId && (
              <span className="text-ink-3">· {state.currentBranch ?? 'detached'}</span>
            )}
          </Link>
        </div>
      </div>
    </header>
  )
}
