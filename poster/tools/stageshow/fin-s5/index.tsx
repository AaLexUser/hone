import { Bar, Button, Stage } from '../../kit'
import '../_hone/hone.css'
import './s5.css'

// Final still 5: Hone's version history of AGENTS.md. Each committed version is
// one row on a commit line, newest first; the version in use carries a quiet
// tag, and the row under the pointer shows its two actions. Type is at least
// 20px so it prints at 8.5 mm or more.

type V = { title: string; meta?: string; inUse?: boolean; hover?: boolean; first?: boolean }
const VERSIONS: V[] = [
  { title: 'fix: drop £0 lines', meta: '1 edit · verified', inUse: true },
  { title: 'fix: keep bold', meta: '2 edits · verified', hover: true },
  { title: 'feat: first four rules', first: true },
]

export default function FinS5() {
  return (
    <Stage width={520} height={230} className="hone s5">
      {() => (
        <div className="s5-card">
          <div className="s5-head">
            <span className="s5-id mono">AGENTS.md</span>
            <span className="s5-sub">version history</span>
          </div>
          <div className="s5-list">
            {VERSIONS.map((v, i) => (
              <div key={i} className="s5-row" data-hover={v.hover || undefined}>
                <span className="s5-node" data-first={v.first || undefined} data-top={i === 0 || undefined} />
                <div className="s5-text">
                  {v.first ? <Bar w={260} h={11} r={5.5} tone={2} /> : <span className="s5-title mono">{v.title}</span>}
                  {v.meta && <span className="s5-meta">{v.meta}</span>}
                </div>
                {v.inUse && <span className="s5-tag">in use</span>}
                {v.hover && (
                  <div className="s5-actions">
                    <Button size="large">Compare</Button>
                    <Button size="large">Roll back</Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Stage>
  )
}
