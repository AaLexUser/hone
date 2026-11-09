import { Check } from 'lucide-react'
import { Stage } from '../../kit'
import '../_hone/hone.css'
import './c1.css'

// Final still: the commit a finished run makes. Left, the judge's commit
// message, title and body; right, the verified diff it applies to AGENTS.md.
// Wide so it prints at 120 mm high with type at 8.5 mm or more (22px).

export default function FinC1() {
  return (
    <Stage width={780} height={300} className="hone c1">
      {() => (
        <div className="c1-card">
          <div className="c1-head">
            <span className="c1-id mono">AGENTS.md</span>
            <span className="c1-ok"><Check size={22} strokeWidth={2.6} /><b>Verified and committed</b></span>
          </div>
          <div className="c1-body">
            <div className="c1-msg">
              <p className="c1-lbl">Judge’s commit message</p>
              <p className="c1-title mono">fix: drop zero-value bonus and equity lines</p>
              <p className="c1-why">Both sessions ask to drop the line; one wider rule replaces the old one.</p>
            </div>
            <div className="c1-diff">
              <p className="c1-line mono" data-kind="del"><span>−</span><span>When a conditional block does not apply, delete the paragraph.</span></p>
              <p className="c1-line mono" data-kind="add"><span>+</span><span>When a block or line does not apply, delete it. Never leave £0 or 0 shares.</span></p>
            </div>
          </div>
        </div>
      )}
    </Stage>
  )
}
