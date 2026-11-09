import { GitBranch } from 'lucide-react'
import { Bar, Button, Stage } from '../../kit'
import '../_hone/hone.css'
import './s5.css'

// Final still 5: Hone's Versions page, as the real one shows it. The commit
// history of AGENTS.md on one line, newest first, each row the judge's commit
// title; the current version is marked, and the selected older one shows the
// page's own actions. Type is at least 20px so it prints at 8.5 mm or more.

type V = { title: string; ago: string; current?: boolean; selected?: boolean; filler?: boolean }
const VERSIONS: V[] = [
  { title: 'fix: drop zero-value bonus and equity lines', ago: '1d ago', current: true },
  { title: 'fix: keep template formatting in DOCX and PDF', ago: '12d ago', selected: true },
  { title: 'feat: add offer-letter rules for dates, gaps, PDF', ago: '18d ago' },
  { title: '', ago: '', filler: true },
]

export default function FinS5() {
  return (
    <Stage width={640} height={318} className="hone s5">
      {() => (
        <div className="s5-card">
          <div className="s5-head">
            <GitBranch size={20} strokeWidth={2.2} className="s5-hicon" />
            <span className="s5-h">History</span>
            <span className="s5-id mono">AGENTS.md</span>
          </div>
          <div className="s5-list">
            {VERSIONS.map((v, i) => (
              <div key={i} className="s5-row" data-selected={v.selected || undefined}>
                <span className="s5-node" data-current={v.current || undefined} data-top={i === 0 || undefined} />
                {v.filler ? <div className="s5-text"><Bar w={300} h={11} r={5.5} tone={2} /><Bar w={90} h={11} r={5.5} tone={1} /></div> : <div className="s5-text">
                  <span className="s5-title">{v.title}</span>
                  <span className="s5-meta">{v.ago}{v.current && <b className="s5-tag">current</b>}</span>
                </div>}
                {v.selected && (
                  <div className="s5-actions">
                    <Button size="large">Set as current</Button>
                    <Button size="large">Branch from here</Button>
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
