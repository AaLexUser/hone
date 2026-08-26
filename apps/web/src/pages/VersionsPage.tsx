import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { GitBranch, GitMerge, Check, Pencil, Copy, GitPullRequestArrow, AlertTriangle, X } from 'lucide-react'
import { useStore, relTime, actions } from '../store'
import { colorOf } from '../data'
import type { VersionNode } from '../data'
import { diffLines } from '../lib/diff'
import { Badge } from '../components/ui'

const ROW_H = 56
const LANE_GAP = 18
const RAIL_PAD = 22
const CURVE_H = 22
const RAIL_W = 2.25

/** All parents of a commit — merge commits carry two. */
const parentsOf = (v: VersionNode) =>
  v.parents?.length ? v.parents : v.parentId ? [v.parentId] : []

/**
 * Row order for the graph: children strictly above their parents, newest
 * first among the ready commits — the same invariant `git log --graph`
 * relies on. Plain date sorting breaks it when timestamps tie or interleave.
 */
function topoOrder(versions: VersionNode[]): VersionNode[] {
  const byId = new Map(versions.map((v) => [v.id, v]))
  const pending = new Map<string, number>(versions.map((v) => [v.id, 0]))
  for (const v of versions) {
    for (const p of parentsOf(v)) {
      if (byId.has(p) && p !== v.id) pending.set(p, (pending.get(p) ?? 0) + 1)
    }
  }
  const ready = versions.filter((v) => pending.get(v.id) === 0)
  const out: VersionNode[] = []
  const placed = new Set<string>()
  while (ready.length) {
    let best = 0
    for (let i = 1; i < ready.length; i++) {
      if (ready[i].createdAt > ready[best].createdAt) best = i
    }
    const v = ready.splice(best, 1)[0]
    out.push(v)
    placed.add(v.id)
    for (const p of parentsOf(v)) {
      if (!placed.has(p) && byId.has(p) && p !== v.id) {
        const n = (pending.get(p) ?? 0) - 1
        pending.set(p, n)
        if (n === 0) ready.push(byId.get(p)!)
      }
    }
  }
  // Safety net for malformed input: never drop a commit from the list.
  for (const v of versions) if (!placed.has(v.id)) out.push(v)
  return out
}

interface Prim {
  key: string
  d: string
  color: string
  dashed?: boolean
}

interface GraphLayout {
  dotCol: number[]
  prims: Prim[]
  cols: number
}

const colX = (col: number) => RAIL_PAD + col * LANE_GAP

/** Smooth vertical S-curve between two points in different columns. */
function curvePath(x1: number, y1: number, x2: number, y2: number) {
  const bend = Math.min(Math.abs(y2 - y1) / 2, 14)
  return `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`
}

/**
 * Column-based git-graph layout, drawn as rails with soft bezier joins —
 * every active edge owns a column, dots only land in free columns, the first
 * parent continues the commit's column, further parents fork off with a
 * curve, merges join existing rails with a curve. Colors follow the branch
 * each rail belongs to.
 */
function layoutGraph(rows: VersionNode[], colorOf: (v: VersionNode) => string): GraphLayout {
  const rowSet = new Set(rows.map((r) => r.id))
  const byId = new Map(rows.map((r) => [r.id, r]))
  type Slot = { parent: string; color: string } | null
  const slots: Slot[] = []
  const lastY: number[] = []
  const dotCol: number[] = []
  const prims: Prim[] = []
  let cols = 0

  const firstFree = () => {
    for (let k = 0; k < slots.length; k++) if (!slots[k]) return k
    slots.push(null)
    return slots.length - 1
  }

  rows.forEach((v, i) => {
    const y = i * ROW_H + ROW_H / 2
    const color = colorOf(v)
    const incoming = slots.map((s, k) => (s && s.parent === v.id ? k : -1)).filter((k) => k >= 0)

    // Rails arriving at this dot: first straight in, the rest J-curve into it.
    let col: number
    if (incoming.length === 0) {
      col = firstFree()
      lastY[col] = y
    } else {
      col = incoming[0]
      incoming.forEach((k, idx) => {
        const x = colX(k)
        const from = lastY[k] ?? y - ROW_H
        if (idx === 0) {
          prims.push({ key: `in-${i}-${k}`, d: `M${x},${from} L${x},${y}`, color: slots[k]!.color })
        } else {
          prims.push({ key: `in-${i}-${k}-rail`, d: `M${x},${from} L${x},${y - CURVE_H}`, color: slots[k]!.color })
          prims.push({ key: `in-${i}-${k}-arc`, d: curvePath(x, y - CURVE_H, colX(col), y), color: slots[k]!.color })
        }
      })
      incoming.forEach((k) => (slots[k] = null))
    }
    dotCol[i] = col
    cols = Math.max(cols, col)

    // Rails of other edges pass straight through this row.
    slots.forEach((s, k) => {
      if (!s || s.parent === v.id) return
      const from = lastY[k]
      if (from !== undefined && from < y) {
        prims.push({ key: `pass-${i}-${k}`, d: `M${colX(k)},${from} L${colX(k)},${y}`, color: s.color })
      }
      lastY[k] = y
    })

    const parents = [...new Set(parentsOf(v))].filter((p) => p !== v.id)
    const isMerge = parents.length > 1
    let first = true
    for (const p of parents) {
      const pColor = byId.has(p) ? colorOf(byId.get(p)!) : color
      if (!rowSet.has(p) || !byId.has(p)) {
        // Parent filtered out (or unknown): the history continues elsewhere.
        prims.push({
          key: `stub-${i}-${p}`,
          d: `M${colX(col)},${y} L${colX(col)},${y + ROW_H * 0.55}`,
          color,
          dashed: true,
        })
        continue
      }
      const existing = slots.findIndex((s) => s && s.parent === p)
      if (existing >= 0) {
        // Join: curve from this dot onto the existing rail, in this commit's color.
        prims.push({ key: `join-${i}-${p}`, d: curvePath(colX(col), y, colX(existing), y + CURVE_H), color })
      } else if (first) {
        // The continuation rail keeps the child's branch color — a branch tip
        // on the trunk reads as its own rail arriving at the trunk dot.
        slots[col] = { parent: p, color }
        lastY[col] = y
      } else {
        // Fork: curve off the dot into a fresh column; merge second parents
        // take the target branch's color, regular continuations the child's.
        const k = firstFree()
        const edgeColor = isMerge ? pColor : color
        slots[k] = { parent: p, color: edgeColor }
        prims.push({ key: `fork-${i}-${p}`, d: curvePath(colX(col), y, colX(k), y + CURVE_H), color: edgeColor })
        lastY[k] = y + CURVE_H
        cols = Math.max(cols, k)
      }
      first = false
    }
  })
  return { dotCol, prims, cols: cols + 1 }
}

interface Menu {
  x: number
  y: number
  branch: string
  versionId?: string
}

export function VersionsPage() {
  const { state, refresh } = useStore()
  const [selectedId, setSelectedId] = useState(state.currentId)
  const [branch, setBranch] = useState<string | null>(null)
  const [tab, setTab] = useState<'diff' | 'file'>('diff')
  const [confirming, setConfirming] = useState(false)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [branching, setBranching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const branches = state.branches
  const all = useMemo(() => topoOrder(state.versions), [state.versions])
  const byId = useMemo(() => new Map(state.versions.map((v) => [v.id, v])), [state.versions])
  const branchOf = (name: string) => branches.find((b) => b.name === name)
  const paint = useCallback((v: VersionNode) => colorOf(v.branch, branches), [branches])

  const present = branches
  const rows = useMemo(() => (branch ? all.filter((v) => v.branch === branch) : all), [all, branch])
  const graph = useMemo(() => layoutGraph(rows, paint), [rows, paint])

  const railW = RAIL_PAD + graph.cols * LANE_GAP

  // A branch name rides on its tip commit, the way git log tags refs.
  const tipsBySha = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const b of branches) m.set(b.tip, [...(m.get(b.tip) ?? []), b.name])
    return m
  }, [branches])

  const selected = byId.get(selectedId) ?? all[0]
  const parent = selected?.parentId ? byId.get(selected.parentId) : undefined
  const diff = useMemo(
    () =>
      parent && selected
        ? diffLines(parent.file, selected.file)
        : (selected?.file ?? []).map((l, i) => ({ type: 'add' as const, a: null, b: i + 1, text: l })),
    [parent, selected],
  )
  const adds = diff.filter((r) => r.type === 'add').length
  const dels = diff.filter((r) => r.type === 'del').length
  const isCurrent = !!selected && selected.id === state.currentId
  const isMerge = !!selected && (selected.parents?.length ?? 0) > 1
  /** Branch whose tip is the selected version — offer merging it into the current branch. */
  const tipBranchOfSelected = selected
    ? branches.find((b) => b.tip === selected.id && !b.current && b.tip !== state.currentId)
    : undefined

  const editCount = (v: VersionNode) => {
    const p = v.parentId ? byId.get(v.parentId) : undefined
    if (!p) return 0
    return diffLines(p.file, v.file).filter((r) => r.type !== 'ctx').length
  }

  const run = async (fn: () => Promise<unknown>, doing: string) => {
    try {
      await fn()
      setError(null)
      refresh()
    } catch (e) {
      setError(`${doing}: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const setCurrent = async () => {
    if (!confirming) {
      setConfirming(true)
      setTimeout(() => setConfirming(false), 2500)
      return
    }
    setConfirming(false)
    await run(() => actions.setCurrent(selected.id), 'git checkout')
  }

  const openMenu = (e: React.MouseEvent, b: string, versionId?: string) => {
    e.preventDefault()
    setMenu({ x: e.clientX, y: e.clientY, branch: b, versionId })
  }

  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 8000)
    return () => clearTimeout(t)
  }, [error])

  if (!selected) {
    return <div className="card px-5 py-10 text-center text-[12.5px] text-ink-3">Loading versions…</div>
  }

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[400px_1fr]">
      {/* History */}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-line px-5 py-3">
          <GitBranch size={13} className="text-ink-3" />
          <span className="text-[13px] font-semibold">History</span>
          <span className="ml-auto font-mono text-[10.5px] text-ink-3">
            {all.length} commits · {present.length} branches · on{' '}
            <span className="text-ink-2">{state.currentBranch ?? 'detached'}</span>
          </span>
        </div>

        {/* Branch legend doubles as the filter; right-click opens git actions */}
        <div className="scrollbar-none flex items-center gap-1 overflow-x-auto border-b border-line px-2.5 py-2">
          <BranchChip active={branch === null} onClick={() => setBranch(null)} label="All" count={all.length} />
          {present.map((b) => (
            <BranchChip
              key={b.name}
              active={branch === b.name}
              onClick={() => setBranch(branch === b.name ? null : b.name)}
              onContextMenu={(e) => openMenu(e, b.name)}
              label={b.name}
              color={b.color}
              count={b.count}
              current={b.current}
            />
          ))}
        </div>

        <div className="relative max-h-[62vh] overflow-x-hidden overflow-y-auto">
          {/* Graph rail: monochrome branch rails with soft bezier forks/joins. */}
          <svg className="pointer-events-none absolute inset-y-0 left-0 z-10" width={railW} height={rows.length * ROW_H}>
            {graph.prims.map((p, i) => (
              <motion.path
                key={p.key}
                d={p.d}
                stroke={p.color}
                strokeOpacity={p.dashed ? 0.35 : 0.85}
                strokeWidth={RAIL_W}
                strokeDasharray={p.dashed ? '3 4' : undefined}
                strokeLinecap="round"
                fill="none"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.4, ease: 'easeOut', delay: Math.min(i, 16) * 0.015 }}
              />
            ))}
            {rows.map((v, i) => {
              const cx = colX(graph.dotCol[i])
              const cy = i * ROW_H + ROW_H / 2
              const current = v.id === state.currentId
              const isSel = v.id === selectedId
              return (
                <motion.g
                  key={v.id}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 26, delay: Math.min(i, 12) * 0.02 }}
                  style={{ transformOrigin: `${cx}px ${cy}px` }}
                >
                  {current && (
                    <circle cx={cx} cy={cy} r={9.5} fill="none" stroke="var(--color-green)" strokeOpacity={0.45} strokeWidth={1.5} />
                  )}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={5}
                    fill={current ? 'var(--color-green)' : paint(v)}
                    stroke="var(--color-panel)"
                    strokeWidth={2.5}
                  />
                  {isSel && !current && (
                    <circle cx={cx} cy={cy} r={8.5} fill="none" stroke={paint(v)} strokeOpacity={0.7} strokeWidth={1.5} />
                  )}
                </motion.g>
              )
            })}
          </svg>

          <AnimatePresence initial={false}>
            {rows.map((v) => (
              <motion.button
                key={v.id}
                layout
                initial={{ opacity: 0, y: -12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                onClick={() => {
                  setSelectedId(v.id)
                  setConfirming(false)
                  setBranching(false)
                }}
                onContextMenu={(e) => openMenu(e, v.branch, v.id)}
                style={{ height: ROW_H, paddingLeft: railW + 12 }}
                className={`hover-row relative flex w-full items-center gap-3 border-b border-line/60 py-2 pr-4 text-left ${
                  v.id === selectedId ? 'bg-white/4' : ''
                }`}
              >
                {v.id === selectedId && (
                  <motion.span
                    layoutId="version-selected"
                    className="absolute inset-y-0 left-0 w-[2px]"
                    style={{ background: paint(v) }}
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[12.5px] text-ink">{v.id}</span>
                    {v.id === state.currentId && <Badge kind="current">current</Badge>}
                    {tipsBySha.get(v.id)?.map((name) => (
                      <BranchTag key={name} branch={name} name={name} />
                    ))}
                  </div>
                  <div className="mt-0.5 truncate text-[11.5px] text-ink-3">
                    {v.title ? (
                      <span className="text-ink-2">{v.title}</span>
                    ) : v.runId ? (
                      `${editCount(v)} ${editCount(v) === 1 ? 'edit' : 'edits'} · run ${v.runId}`
                    ) : (
                      'seed file'
                    )}{' '}
                    · {relTime(v.createdAt)}
                  </div>
                </div>
              </motion.button>
            ))}
          </AnimatePresence>
        </div>
      </div>

      {/* Detail */}
      <AnimatePresence mode="wait">
        <motion.div
          key={selected.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
          className="card static overflow-hidden lg:sticky lg:top-[76px]"
        >
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-[14px] font-medium">{selected.id}</span>
                <button onContextMenu={(e) => openMenu(e, selected.branch, selected.id)} title="Right-click for branch actions">
                  <BranchTag branch={selected.branch} name={selected.branch} />
                </button>
                {isMerge && (
                  <span className="flex items-center gap-1 rounded-[4px] border border-line-2 px-1.5 py-px text-[10px] text-ink-3">
                    <GitMerge size={9} /> merge
                  </span>
                )}
                {isCurrent && <Badge kind="current">current</Badge>}
              </div>
              {selected.title && (
                <div className="mt-1 font-mono text-[12px] text-ink-2">{selected.title}</div>
              )}
              <div className="mt-0.5 text-[11.5px] text-ink-3">
                {relTime(selected.createdAt)}
                {parent && (
                  <>
                    {' '}
                    · parent <span className="font-mono">{parent.id}</span>
                  </>
                )}
                {isMerge && selected.parents && (
                  <>
                    {' '}
                    · merged from <span className="font-mono">{selected.parents.slice(1).join(', ')}</span>
                  </>
                )}
                {selected.runId && (
                  <>
                    {' '}
                    · run{' '}
                    <Link
                      to={`/runs/${selected.runId}`}
                      className="font-mono text-[#8b95f6] hover:underline"
                      title="Open the run that produced this commit"
                    >
                      {selected.runId}
                    </Link>
                  </>
                )}
              </div>
            </div>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
              {tipBranchOfSelected && (
                <motion.button
                  onClick={() => run(() => actions.mergeBranch(tipBranchOfSelected.name), `merge ${tipBranchOfSelected.name}`)}
                  whileTap={{ scale: 0.98 }}
                  title={`Merge branch ${tipBranchOfSelected.name} into ${state.currentBranch ?? 'current'}`}
                  className="btn-ghost flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] text-ink-2"
                >
                  <GitMerge size={13} /> Merge {tipBranchOfSelected.name}
                </motion.button>
              )}
              <motion.button
                onClick={() => setBranching((b) => !b)}
                whileTap={{ scale: 0.98 }}
                className="btn-ghost flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] text-ink-2"
              >
                <GitBranch size={13} /> Branch from here
              </motion.button>
              {isCurrent ? (
                <span className="flex items-center gap-1.5 px-2 text-[12px] text-green">
                  <Check size={13} /> serving at /agents.md
                </span>
              ) : (
                <motion.button
                  onClick={setCurrent}
                  whileTap={{ scale: 0.98 }}
                  className={
                    confirming
                      ? 'btn-primary rounded-md px-3 py-1.5 text-[12px] font-medium text-white'
                      : 'btn-ghost rounded-md px-3 py-1.5 text-[12px] text-ink-2'
                  }
                >
                  {confirming ? 'Confirm — set as current' : 'Set as current'}
                </motion.button>
              )}
            </div>
          </div>

          <AnimatePresence>
            {(branching || error) && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden border-b border-line"
              >
                {branching && (
                  <NewBranchForm
                    at={selected.id}
                    onCancel={() => setBranching(false)}
                    onCreate={(name) =>
                      run(async () => {
                        await actions.createBranch(name, selected.id)
                        setBranching(false)
                      }, `branch ${name}`)
                    }
                  />
                )}
                {error && (
                  <div className="flex items-start gap-2 px-5 py-2.5 text-[12px] text-red">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    <span className="leading-relaxed">{error}</span>
                    <button onClick={() => setError(null)} className="ml-auto shrink-0 text-ink-3 hover:text-ink">
                      <X size={13} />
                    </button>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="flex items-center gap-1 border-b border-line px-3 py-1.5">
            {(['diff', 'file'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className="relative rounded-md px-2.5 py-1 text-[12px]">
                {tab === t && (
                  <motion.span
                    layoutId="version-tab"
                    className="absolute inset-0 rounded-md bg-white/6"
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <span className={`relative ${tab === t ? 'text-ink' : 'text-ink-3 hover:text-ink-2'}`}>
                  {t === 'diff' ? 'Diff vs parent' : 'Full file'}
                </span>
              </button>
            ))}
            {tab === 'diff' && (
              <span className="ml-auto pr-2 font-mono text-[11px]">
                <span className="text-green">+{adds}</span> <span className="text-red">−{dels}</span>
              </span>
            )}
          </div>

          <div className="max-h-[58vh] overflow-auto py-2 font-mono text-[12px] leading-[1.75]">
            {tab === 'diff'
              ? diff.map((row, i) => (
                  <motion.div
                    key={`${selected.id}-${i}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.015, duration: 0.2 }}
                    className={`flex gap-3 px-5 ${
                      row.type === 'add'
                        ? 'bg-green/8 text-green'
                        : row.type === 'del'
                          ? 'bg-red/8 text-red/85 line-through'
                          : 'text-ink-2'
                    }`}
                  >
                    <span className="w-6 shrink-0 text-right text-ink-3/50 select-none">{row.a ?? ''}</span>
                    <span className="w-6 shrink-0 text-right text-ink-3/50 select-none">{row.b ?? ''}</span>
                    <span className="w-3 shrink-0 select-none">
                      {row.type === 'add' ? '+' : row.type === 'del' ? '−' : ''}
                    </span>
                    <span className="whitespace-pre-wrap">{row.text || ' '}</span>
                  </motion.div>
                ))
              : selected.file.map((line, i) => (
                  <motion.div
                    key={`${selected.id}-f-${i}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.012, duration: 0.2 }}
                    className="flex gap-3 px-5 text-ink-2"
                  >
                    <span className="w-6 shrink-0 text-right text-ink-3/50 select-none">{i + 1}</span>
                    <span className={`whitespace-pre-wrap ${line.startsWith('#') ? 'font-semibold text-ink' : ''}`}>
                      {line || ' '}
                    </span>
                  </motion.div>
                ))}
          </div>
        </motion.div>
      </AnimatePresence>

      <AnimatePresence>
        {menu && (
          <BranchMenu
            menu={menu}
            count={branchOf(menu.branch)?.count ?? 0}
            isCurrentBranch={branchOf(menu.branch)?.current ?? false}
            onClose={() => setMenu(null)}
            onRename={(to) => run(() => actions.renameBranch(menu.branch, to), `rename ${menu.branch}`)}
            onMerge={() => run(() => actions.mergeBranch(menu.branch), `merge ${menu.branch}`)}
            onBranchFrom={(name) =>
              run(() => actions.createBranch(name, menu.versionId), `branch ${name}`)
            }
          />
        )}
      </AnimatePresence>
    </div>
  )
}

function BranchTag({ branch, name }: { branch: string; name: string }) {
  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 480, damping: 26 }}
      className="rounded-[4px] border px-1.5 py-px text-[10px] font-medium"
      style={{ color: colorOf(branch), borderColor: `${colorOf(branch)}55`, background: `${colorOf(branch)}14` }}
    >
      {name}
    </motion.span>
  )
}

function BranchChip({
  label,
  count,
  color,
  active,
  current,
  onClick,
  onContextMenu,
}: {
  label: string
  count: number
  color?: string
  active: boolean
  current?: boolean
  onClick: () => void
  onContextMenu?: (e: React.MouseEvent) => void
}) {
  return (
    <button
      onClick={onClick}
      onContextMenu={onContextMenu}
      title={color ? 'Click to filter · right-click for git actions · count = commits authored on this branch' : undefined}
      className="relative shrink-0 rounded-md px-2 py-1 text-[11.5px]"
    >
      {active && (
        <motion.span
          layoutId="branch-pill"
          className="absolute inset-0 rounded-md bg-white/7"
          transition={{ type: 'spring', stiffness: 500, damping: 38 }}
        />
      )}
      <span className={`relative flex items-center gap-1.5 ${active ? 'text-ink' : 'text-ink-3 hover:text-ink-2'}`}>
        {color && <span className="size-1.5 rounded-full" style={{ background: color }} />}
        <span className="font-mono text-[11px]">{label}</span>
        {current && <span className="text-[9px] text-green">●</span>}
        <span className="font-mono text-[10px] text-ink-3">{count}</span>
      </span>
    </button>
  )
}

function NewBranchForm({
  at,
  onCreate,
  onCancel,
}: {
  at: string
  onCreate: (name: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div className="flex items-center gap-2 px-5 py-2.5">
      <GitPullRequestArrow size={13} className="shrink-0 text-ink-3" />
      <span className="shrink-0 text-[12px] text-ink-3">
        New branch at <span className="font-mono text-ink-2">{at}</span>
      </span>
      <input
        ref={ref}
        value={name}
        maxLength={40}
        onChange={(e) => setName(e.target.value.replace(/[^\w./-]/g, '-'))}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && name.trim()) onCreate(name.trim())
          if (e.key === 'Escape') onCancel()
        }}
        placeholder="branch name"
        className="h-7 flex-1 rounded-md border border-line-2 bg-panel-2 px-2 font-mono text-[12px] text-ink outline-none focus:border-[#7d89f0]"
      />
      <button
        onClick={() => name.trim() && onCreate(name.trim())}
        disabled={!name.trim()}
        className="btn-primary rounded-md px-2.5 py-1 text-[11.5px] font-medium text-white disabled:opacity-40"
      >
        Create branch
      </button>
      <button onClick={onCancel} className="btn-ghost rounded-md px-2 py-1 text-[11.5px] text-ink-2">
        Cancel
      </button>
    </div>
  )
}

/** Right-click menu — git actions on the branch (and the version it was opened on). */
function BranchMenu({
  menu,
  count,
  isCurrentBranch,
  onClose,
  onRename,
  onMerge,
  onBranchFrom,
}: {
  menu: Menu
  count: number
  isCurrentBranch: boolean
  onClose: () => void
  onRename: (to: string) => void
  onMerge: () => void
  onBranchFrom: (name: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [editing, setEditing] = useState<'none' | 'rename' | 'branch'>('none')
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onClose, true)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [onClose])

  const commit = (action: () => void) => {
    action()
    onClose()
  }

  const x = Math.min(menu.x, window.innerWidth - 248)
  const y = Math.min(menu.y, window.innerHeight - 220)

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, scale: 0.96, y: -4 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.1 } }}
      transition={{ type: 'spring', stiffness: 520, damping: 32 }}
      style={{ left: x, top: y, transformOrigin: 'top left' }}
      className="card fixed z-50 w-60 p-1 shadow-[0_16px_40px_rgba(0,0,0,0.55)]"
    >
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className="size-1.5 shrink-0 rounded-full" style={{ background: colorOf(menu.branch) }} />
        <span className="truncate font-mono text-[11.5px] text-ink">{menu.branch}</span>
        {isCurrentBranch && <span className="ml-auto text-[9px] text-green">current</span>}
        <span className={`font-mono text-[10px] text-ink-3 ${isCurrentBranch ? '' : 'ml-auto'}`}>{count}</span>
      </div>
      <div className="my-1 h-px bg-line" />

      {editing !== 'none' ? (
        <div className="p-1">
          <input
            autoFocus
            value={draft}
            maxLength={40}
            onChange={(e) => setDraft(e.target.value.replace(/[^\w./-]/g, '-'))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && draft.trim()) {
                commit(() =>
                  editing === 'rename' ? onRename(draft.trim()) : onBranchFrom(draft.trim()),
                )
              }
              if (e.key === 'Escape') onClose()
            }}
            placeholder={editing === 'rename' ? 'new branch name' : 'branch name'}
            className="h-7 w-full rounded-md border border-line-2 bg-panel-2 px-2 font-mono text-[12px] text-ink outline-none focus:border-[#7d89f0]"
          />
          <div className="mt-1 flex items-center gap-1">
            <button
              onClick={() => draft.trim() && commit(() =>
                editing === 'rename' ? onRename(draft.trim()) : onBranchFrom(draft.trim()),
              )}
              className="btn-primary flex-1 rounded-md px-2 py-1 text-[11.5px] font-medium text-white"
            >
              {editing === 'rename' ? 'Rename' : 'Create'}
            </button>
            <button onClick={onClose} className="btn-ghost rounded-md px-2 py-1 text-[11.5px] text-ink-2">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <MenuItem
            icon={GitMerge}
            label={`Merge into ${isCurrentBranch ? '… (is current)' : 'current branch'}`}
            disabled={isCurrentBranch}
            onClick={() => commit(onMerge)}
          />
          <MenuItem
            icon={Pencil}
            label="Rename branch…"
            onClick={() => {
              setDraft(menu.branch)
              setEditing('rename')
            }}
          />
          {menu.versionId && (
            <MenuItem
              icon={GitBranch}
              label="New branch from this version…"
              onClick={() => {
                setDraft('')
                setEditing('branch')
              }}
            />
          )}
          {menu.versionId && (
            <MenuItem
              icon={Copy}
              label="Copy version id"
              onClick={() => {
                navigator.clipboard?.writeText(menu.versionId!)
                onClose()
              }}
            />
          )}
        </>
      )}
    </motion.div>
  )
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: typeof Pencil
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12px] text-ink-2 transition-colors hover:bg-white/6 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
    >
      <Icon size={12} className="shrink-0 text-ink-3" />
      {label}
    </button>
  )
}
