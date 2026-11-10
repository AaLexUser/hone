// Folds every seeded run's events.jsonl through the page's real reducer and selectors and asserts what the page shows.
// Usage: node scripts/check-run-model.mjs <hone data dir> [<hone data dir> ...]
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createJiti } from 'jiti'

const here = path.dirname(fileURLToPath(import.meta.url))
const jiti = createJiti(import.meta.url)
const { parseRunEvent } = await jiti.import(path.join(here, '../src/run/events.ts'))
const { initialModel, isTerminal, reduceRun } = await jiti.import(path.join(here, '../src/run/model.ts'))
const { attemptStories, crossExam, laneGroups, nowLine, seatStatus, stageState, verifyState } = await jiti.import(
  path.join(here, '../src/run/derive.ts'),
)
const { graphLayout } = await jiti.import(path.join(here, '../src/run/graph/layout.ts'))
const { activityRows } = await jiti.import(path.join(here, '../src/run/activity.ts'))

const dirs = process.argv.slice(2)
if (!dirs.length) {
  console.error('usage: node scripts/check-run-model.mjs <hone data dir> [...]')
  process.exit(2)
}

const lines = (file) => fs.readFileSync(file, 'utf8').trim().split('\n')
const parse = (raw) => raw.map(parseRunEvent).filter((e) => e !== null)
const fold = (events) => reduceRun(initialModel, events)

const askRows = (events) => activityRows(fold(events)).filter((r) => r.type === 'ask')
const answerIds = (asks) => asks.flatMap((a) => a.turns.flatMap((t) => (t.answer ? [t.answer.id] : []))).sort()

/** Each judge question sits right above its own seat's answer, and a run without questions nests the same answers. */
function checkCrossExam(raw, events, terminal) {
  const asks = askRows(events)
  for (const a of asks) {
    for (const t of a.turns) {
      if (t.answer) assert.equal(t.answer.seat.key, t.seat.key, 'an answer sits under the question to its own seat')
      if (terminal && t.question) assert.ok(t.answer, `the question to ${t.seat.key} got an answer row`)
    }
  }
  const unasked = parse(raw.map((l) => {
    const r = JSON.parse(l)
    delete r.queries
    return JSON.stringify(r)
  }))
  const old = askRows(unasked)
  assert.ok(old.every((a) => a.turns.every((t) => t.question === null)), 'a run without queries shows no questions')
  assert.deepEqual(answerIds(old), answerIds(asks), 'a run without queries nests the same answers')
  return asks.reduce((n, a) => n + a.turns.filter((t) => t.question).length, 0)
}

/** Panel sizes from hone.yaml: the `- model:` entries under each stage's `panel:`. */
function roster(dir) {
  const yaml = fs.readFileSync(path.join(dir, 'hone.yaml'), 'utf8')
  const panel = (stage) => {
    const block = yaml.split(new RegExp(`\\n  ${stage}:\\n`))[1] ?? ''
    return (block.split(/\n    judge:/)[0].match(/- model:/g) ?? []).length
  }
  return { k: panel('review'), m: panel('propose') }
}

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h
const MIN_CLEAR = 32

/** The card graph has exactly K and M seat cards, each inside its stage box, nothing overlapping, and room around every box. */
function checkLayout(L, k, m) {
  const [rev, pro] = L.groups
  assert.equal(rev.panel.length, k, 'K reviewer cards')
  assert.equal(pro.panel.length, m, 'M proposer cards')
  const view = { x: 0, y: 0, w: L.w, h: L.h }
  const io = [L.traces, L.report, L.verify, L.commit]
  const cards = [...io, ...L.groups.flatMap((g) => [...g.panel.map((p) => p.box), ...(g.judge ? [g.judge.box] : [])])]
  for (const c of cards) assert.ok(inside(c, view), 'every card inside the viewBox')
  cards.forEach((a, i) => cards.slice(i + 1).forEach((b) => assert.ok(!overlap(a, b), 'no two cards overlap')))
  for (const g of L.groups) {
    assert.ok(inside(g.box, view), 'every stage box inside the viewBox')
    for (const p of [...g.panel, ...(g.judge ? [g.judge] : [])]) assert.ok(inside(p.box, g.box), 'seat card inside its stage box')
    for (const c of io) {
      const clear = Math.max(c.x - (g.box.x + g.box.w), g.box.x - (c.x + c.w))
      assert.ok(clear >= MIN_CLEAR, `stage box keeps ${MIN_CLEAR}px from its neighbours (got ${clear.toFixed(1)})`)
    }
  }
  assert.ok(!overlap(rev.box, pro.box), 'stage boxes apart')
}

const EXPECT = {
  r_11ac: (m) => {
    assert.equal(m.outcome, 'succeeded')
    assert.equal(m.attempts.length, 1)
    assert.equal(verifyState(m), 'passed')
  },
  r_00bd: (m) => {
    assert.equal(m.outcome, 'succeeded')
    assert.equal(m.attempts.length, 2)
    const [first] = attemptStories(m)
    assert.equal(first.state, 'crashed', 'attempt 1 crashed, never verified')
    const proposers = laneGroups(m)[1].panel
    assert.equal(first.seat?.key, proposers.at(-1).key, 'the failing seat (the seeder sinks the last proposer) is named')
    assert.equal(first.cause, 'provider error')
    const cross = crossExam(m, 'propose')
    const late = proposers.filter((s) => cross[s.key]?.timedOut)
    assert.equal(late.length, 1, 'one proposer timed out on the follow-up')
    assert.ok(proposers.some((s) => cross[s.key]?.answered), 'another proposer answered it')
    assert.equal(seatStatus(m, late[0]), 'done', 'a follow-up timeout does not fail the seat')
  },
  r_008f: (m) => {
    assert.equal(m.outcome, 'no-changes')
    assert.equal(verifyState(m), 'skipped')
  },
  r_1cd0: (m) => {
    if (m.outcome === 'failed') {
      assert.ok(attemptStories(m).every((a) => a.state === 'crashed'), 'a failed replay never reached the verifier')
      assert.equal(verifyState(m), 'skipped', 'no verifier verdict when the verifier never ran')
      assert.equal(stageState(m, 'propose'), 'failed')
    } else {
      assert.equal(m.outcome, 'succeeded')
      assert.equal(verifyState(m), 'passed')
    }
  },
}

let checked = 0
for (const dir of dirs) {
  const { k, m: mm } = roster(dir)
  for (const run of fs.readdirSync(path.join(dir, 'runs')).sort()) {
    const file = path.join(dir, 'runs', run, 'events.jsonl')
    if (!fs.existsSync(file)) continue
    const raw = lines(file)
    const events = parse(raw)
    const m = fold(events)
    const where = `${path.basename(dir)}/${run}`
    try {
      const [review, propose] = laneGroups(m)
      assert.equal(review.panel.length, k, 'K reviewer seats from the roster')
      assert.equal(propose.panel.length, mm, 'M proposer seats from the roster')
      assert.ok(review.judge && propose.judge, 'one judge per stage')
      checkLayout(graphLayout([review, propose]), k, mm)
      assert.equal(m.events.length, events.length, 'every event kept')
      if (isTerminal(m.outcome)) {
        assert.equal(nowLine(m, 3), null, 'no now-line after the end')
        assert.ok(m.followUps.every((f) => f.end !== null), 'every follow-up closed')
        assert.ok(Object.values(m.lanes).every((l) => l.spans.every((s) => s.end !== null)), 'every span closed')
      }

      const half = Math.floor(events.length / 2)
      assert.deepEqual(reduceRun(fold(events.slice(0, half)), events.slice(half)), m, 'batch-invariant')
      assert.deepEqual(reduceRun(m, events), m, 'a stream restarted from byte 0 folds to the same model')

      const noAnalytics = parse(raw.filter((l) => !l.includes('"kind": "analytics"') && !l.includes('"kind":"analytics"')))
      assert.ok(fold(noAnalytics).followUps.every((f) => f.end !== null), 'tool_result alone closes a follow-up')

      const crash = events.findIndex((e) => e.kind === 'log' && /^Attempt \d+ stage failed/.test(e.text))
      if (crash >= 0) {
        const mid = fold(events.slice(0, crash + 1))
        assert.notEqual(verifyState(mid), 'rejected', 'a crashed attempt never shows a verifier verdict')
        if (mid.outcome !== 'failed') assert.equal(verifyState(mid), 'pending', 'a crashed attempt leaves Verify pending')
      }

      // Every prefix reduces without throwing and gives a now-line while live.
      for (let i = 1; i < events.length; i += Math.max(1, Math.floor(events.length / 40))) {
        const p = fold(events.slice(0, i))
        if (!isTerminal(p.outcome)) assert.ok(nowLine(p, 3)?.text, `now-line at event ${i}`)
      }

      const questions = checkCrossExam(raw, events, isTerminal(m.outcome))

      EXPECT[run]?.(m)
      checked++
      const ce = laneGroups(m).map((g) => g.panel.reduce((n, s) => n + (crossExam(m, g.stage)[s.key]?.answered ?? 0), 0))
      console.log(
        where.padEnd(24),
        m.outcome.padEnd(11),
        `K=${k} M=${mm}`,
        `attempts=${m.attempts.length}`,
        `verify=${verifyState(m)}`,
        `follow-up answers=${ce.join('/')}`,
        `questions=${questions}`,
      )
    } catch (err) {
      console.error(`FAIL ${where}: ${err.message}`)
      process.exitCode = 1
    }
  }
}

// A 6/6 roster mid-review: the groups come from the roster alone.
const seat = (stage, role, n) => ({ key: `${stage}-${n}`, model: `x/m${n}@high`, role, stage })
const six = ['review', 'propose'].flatMap((stage) => [
  ...[1, 2, 3, 4, 5, 6].map((n) => seat(stage, stage === 'review' ? 'reviewer' : 'proposer', n)),
  { key: `${stage}-judge`, model: 'x/j@high', role: 'judge', stage },
])
const m6 = fold([
  { kind: 'pipeline', at: 1, attempt: 1, agents: six },
  { kind: 'stage', at: 2, stage: 'review', status: 'start' },
  ...[1, 2, 3, 4, 5, 6].map((n) => ({ kind: 'agent_start', at: 10 + n, agent: `review-${n}` })),
])
const [r6, p6] = laneGroups(m6)
const longModel = (n) => ({ key: `x-${n}`, stage: 'review', judge: false, n, model: 'provider/a-much-longer-model-name-v9@high' })
for (let k = 1; k <= 6; k++) {
  for (let mm = 1; mm <= 6; mm++) {
    const g = (stage, n, model) => ({
      stage,
      judge: { key: `${stage}-j`, stage, judge: true, n: 0, model: 'x/gpt-5.4-mini@high' },
      panel: Array.from({ length: n }, (_, i) => ({ key: `${stage}-${i}`, stage, judge: false, n: i + 1, model })),
    })
    checkLayout(graphLayout([g('review', k, 'x/deepseek-v4.1-flash@high'), g('propose', mm, 'x/glm-5.2@high')]), k, mm)
  }
}
checkLayout(graphLayout([{ stage: 'review', judge: null, panel: [1, 2, 3].map(longModel) }, { stage: 'propose', judge: null, panel: [] }]), 3, 0)
console.log('layout 1..6 x 1..6'.padEnd(24), 'cards fit, no overlap, boxes clear')
assert.equal(r6.panel.length, 6)
assert.equal(p6.panel.length, 6)
assert.equal(nowLine(m6, 4).text, '6 reviewers reading 4 sessions')
console.log('synthetic 6/6'.padEnd(24), 'live line:', JSON.stringify(nowLine(m6, 4).text))

if (!checked) {
  console.error('no runs found')
  process.exitCode = 1
}
if (!process.exitCode) console.log(`all checks passed (${checked} runs)`)
