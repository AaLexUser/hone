import { Check } from 'lucide-react'
import { Bar, Stage } from '../../kit'
import '../_hone/hone.css'
import './s4.css'

// Final still 4: the AGENTS.md version Hone committed, as its Versions page
// shows it: the file with the verifier's pass beside it, the commit title,
// then the diff with one rule removed and its widened replacement added
// (both abridged from the scripted demo). Branch and "current" chips and line
// numbers are gone: they mean nothing on a poster. Type is at least 22px.
// Pinned layout: the card is inset top and sides and runs off the bottom,
// where an unchanged context line bleeds as filler.

const DEL = 'When a conditional block does not apply, delete the whole paragraph…'
const ADD = 'When a block or line does not apply, delete it with its label, e.g. a row whose amount is 0. Never leave £0 or 0 shares.'

function Code({ text }: { text: string }) {
  // Backtick spans in AGENTS.md render a shade darker, as Hone's diff does
  const parts = text.split(/(£0|0 shares|\b0\b(?=\.))/)
  return <>{parts.map((p, i) => (i % 2 ? <span key={i} className="s4-tick">{p}</span> : p))}</>
}

export default function FinS4() {
  return (
    <Stage width={560} height={380} className="hone s4">
      {() => (
        <div className="s4-card">
          <div className="s4-head">
            <div className="s4-idrow">
              <span className="s4-id mono">AGENTS.md</span>
              <span className="s4-verified">
                <Check size={22} strokeWidth={2.6} />
                <b>Verified</b>
              </span>
            </div>
            <div className="s4-title mono">fix: drop zero-value bonus and equity lines from offer letters</div>
          </div>
          <div className="s4-diff">
            <div className="s4-line" data-kind="del">
              <span className="s4-sign mono">−</span>
              <span className="s4-text mono"><Code text={DEL} /></span>
            </div>
            <div className="s4-line" data-kind="add">
              <span className="s4-sign mono">+</span>
              <span className="s4-text mono"><Code text={ADD} /></span>
            </div>
            <div className="s4-line s4-line--ctx">
              <span className="s4-sign" />
              <span className="s4-text"><Bar w={300} h={9} r={4.5} tone={2} /></span>
            </div>
          </div>
        </div>
      )}
    </Stage>
  )
}
