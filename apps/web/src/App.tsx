import { useEffect } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { Header } from './components/Layout'
import { pageWidth } from './lib/pageWidth'
import { tellParent } from './lib/embed'
import { Dashboard } from './pages/Dashboard'
import { TracePage } from './pages/TracePage'
import { RunPage } from './pages/RunPage'
import { RunsPage } from './pages/RunsPage'
import { VersionsPage } from './pages/VersionsPage'

export default function App() {
  const location = useLocation()
  useEffect(() => tellParent({ type: 'route', path: location.pathname }), [location.pathname])
  return (
    <div className="min-h-screen">
      <Header />
      <AnimatePresence mode="wait" initial={false}>
        <motion.main
          key={location.pathname}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className={`mx-auto px-4 py-5 sm:px-6 sm:py-7 ${pageWidth(location.pathname)}`}
        >
          <Routes location={location}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/traces/:id" element={<TracePage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:id" element={<RunPage />} />
            <Route path="/versions" element={<VersionsPage />} />
          </Routes>
        </motion.main>
      </AnimatePresence>
    </div>
  )
}
