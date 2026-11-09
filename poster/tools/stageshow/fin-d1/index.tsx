import { MessageSquare, ThumbsUp } from 'lucide-react'
import { Button, Stage } from '../../kit'
import '../_hone/hone.css'
import './d1.css'

// Final still: Hone's dashboard. Finished sessions arrive with the user's
// comments; three of them fill the batch, and the run starts from the
// primary button. Type is at least 21px so it prints at 8.5 mm or more.

type S = { text?: string; kind: 'comment' | 'ok' | 'none' }
const SESSIONS: S[] = [
  { text: 'There’s a ‘£0’ sign-on bonus line…', kind: 'comment' },
  { text: '‘0 shares’ looks odd, drop the line…', kind: 'comment' },
  { text: 'Perfect, that’s exactly it', kind: 'ok' },
]

export default function FinD1() {
  return (
    <Stage width={500} height={400} className="hone d1">
      {() => (
        <div className="d1-card">
          <div className="d1-head">
            <span className="d1-h">Unanalyzed traces</span>
            <span className="d1-new">3</span>
          </div>
          <div className="d1-list">
            {SESSIONS.map((s, i) => (
              <div key={i} className="d1-row">
                <span className="d1-ic" data-kind={s.kind}>
                  {s.kind === 'ok' ? <ThumbsUp size={20} strokeWidth={2.2} /> : <MessageSquare size={20} strokeWidth={2.2} />}
                </span>
                <span className="d1-fb">{s.text}</span>
              </div>
            ))}
          </div>
          <div className="d1-foot">
            <div className="d1-batch">
              <span className="d1-bl">Batch</span>
              <span className="d1-meter"><i /><i /><i /></span>
              <span className="d1-bn">3 / 3</span>
            </div>
            <Button variant="primary" size="large">Start optimization</Button>
          </div>
        </div>
      )}
    </Stage>
  )
}
