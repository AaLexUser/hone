import { Copy, FileText, GitFork, ThumbsDown, ThumbsUp, PanelRight, Columns2 } from 'lucide-react'
import { Bar, Button, Popover, Stage, Text, Window } from '../../kit'
import '../_hone/hone.css'
import './s1.css'

// Final still 1: the user comments on the agent's reply. The reply's file,
// its thumbs-down pressed and the feedback popover with the comment typed.
// The window chrome keeps only its traffic lights and two quiet tool icons;
// the AGENTS.md status chip is gone because it means nothing on a poster.
// Type is at least 22px so it prints at 8.5 mm or more.

const COMMENT = "There's a '£0' sign-on bonus line. If there's no bonus, just leave the line out."

export default function FinS1() {
  return (
    <Stage width={440} height={430} className="hone s1">
      {() => (
        <div className="s1-zoom"><Window
          className="s1-win"
          toolbar={
            <span className="s1-tools">
              <span className="s1-tool"><PanelRight size={15} strokeWidth={1.75} /></span>
              <span className="s1-tool"><Columns2 size={15} strokeWidth={1.75} /></span>
            </span>
          }
        >
          <div className="s1-body">
            <div className="s1-reply">
              <span className="s1-created">Created</span>
              <span className="s1-file"><FileText size={15} strokeWidth={1.9} />Offer_letter.docx</span>
            </div>
            <div className="s1-actions">
              <span className="s1-act"><Copy size={15} strokeWidth={1.75} /></span>
              <span className="s1-act"><GitFork size={15} strokeWidth={1.75} /></span>
              <span className="s1-act"><ThumbsUp size={15} strokeWidth={1.75} /></span>
              <span className="s1-act" data-open data-target="down"><ThumbsDown size={15} strokeWidth={1.75} /></span>
              <Bar w={64} h={7} r={3.5} tone={2} className="s1-time" />
            </div>
            <Popover show origin="top left" className="s1-pop">
              <div className="s1-q">What should the agent do differently next time?</div>
              <div className="s1-area">
                <Text wrap className="s1-typed">{COMMENT}</Text>
                <span className="s1-caret" />
              </div>
              <div className="s1-send">
                <Button variant="primary" className="s1-btn">Send to Hone</Button>
              </div>
            </Popover>
          </div>
        </Window></div>
      )}
    </Stage>
  )
}
