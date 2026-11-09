# Booth demo plan

ICDM 2026 demo session, Saturday 14 November, 13.30 to 16.10 Beijing time, Beijing Room, Wanda Vista Shenyang.
The demo runs on the author's laptop. No TV is booked, so everything is shown on the laptop screen at 125 to 150 percent browser zoom.

## Requirements from the author

1. No scripts and no command line at the booth. Every demo action is a button in the interface.
   One button starts the prepared demo scenario. One button rewinds it to the start for the next visitor.
   The interface is adapted for the demo wherever that helps.
2. The scenario is ordinary white collar work with real office files such as DOCX, PDF and XLSX, not a single JSON file.
   The scenario files sit in the interface, and the presenter drags them straight into the chat window.
3. Restarting t3code, or pressing the reset button, starts the scenario from zero.
   It loads the scenario chats into t3code together with their files, so the presenter can open any chat and show that it is real.
   The prepared scenario then plays exactly as designed.
4. The presenter can also start a completely new conversation and show real work with the live agent.
   After that, a reset brings everything back to the prepared state for the next visitor.
5. The Hone optimizer is embedded in t3code as a web view.
   A new Hone optimization button sits next to the Settings, Usage and PR buttons and opens the Hone interface inside t3code.

## One visitor, about three minutes

1. Request. In t3code the presenter drags the scenario files into the chat and asks the agent for the document. The agent works live for about a minute.
   The Hone chip in the chat header shows the AGENTS.md version and how full the next batch is.
2. Feedback. The presenter opens the result in the chat, points at what is wrong, presses thumbs down and writes a plain sentence.
   A toast confirms that the session reached Hone.
3. Optimization. A real run takes 13 to 24 minutes, so the booth plays a prepared run through Hone's own code in about a minute.
   The run page shows the reviewers, the judge questioning them, the proposers and the verifier.
4. Commit. The Versions page shows the new AGENTS.md version with its diff.
5. For visitors who stay, earlier runs show the cross examination at work.
   Hone held back an edit no feedback supported, refused to turn a one off request into a rule, and changed nothing when nothing was wrong.

## Known gaps to close before the booth

- The prepared replay requires exactly its own unanalyzed sessions. A live visitor session in the same Hone breaks it, so the replay must freeze only its own sessions.
- The visitor's live feedback should match the prepared run's commit, so the scenario files need a case that produces the same complaint.
- A full real optimization run has not been seen end to end in the development container, because Docker builds fail behind its proxy.
  The chip's optimizing state and its AGENTS.md updated toast are unverified. Run one real optimization on the laptop before the trip.
- If the conference Wi-Fi fails, the live agent cannot reach its model. Keep a prepared chat with feedback already given and a screen recording of the whole loop.
- Rotate the OpenCode key after the conference.

## Design

### One source of truth
The scenario lives in the Hone package (`packages/hone/demo/`), moved there from `scripts/dev/seed_runs.py`.
It builds three things from the same hire table, so they always agree.
- The Hone data dir with its history of sessions, feedback and runs.
- One Pi session JSONL per prepared chat. Hone ingests the same JSONL as its trace, so a t3code chat and its Hone trace are one session.
- The project folder. Office input files sit in `Inbox/` and the documents the prepared chats produced sit at the top level.
  Every output document is real. The generator runs the very commands the transcripts show, so the files match the chats.

### Office scenario
An HR coordinator turns hiring approvals into offer letters.
Each hire has a one page `Hiring approval <First Last>.pdf` signed by the department head. All letters use `Offer letter template.docx`.
The agent reads the PDF with `pdftotext`, fills the template with python-docx and exports PDFs with LibreOffice.
`Inbox/` also holds the approval for one more hire, with no bonus and no equity, for the live chat at the booth.
The agent most likely writes zero value rows for that hire, which is the complaint the prepared run turns into a rule.

### Demo mode in Hone
Enabled with `HONE_DEMO=1`. Nothing changes when it is off.
- `POST /api/demo/reset` (write token) restores the prepared state for today's date and returns the manifest below.
  Hone builds the prepared data dir once per day in a child process and caches it, and a reset copies the cache over the live data dir and reopens it.
  Open dashboards reload on a `demo_reset` bus event.
- `POST /api/demo/replay` (write token) plays the prepared run through Hone's own run loop, about a minute long.
  Only that run uses the scripted executor. Start optimization keeps the real MAJICS pipeline.
  The prepared run freezes the whole unanalyzed batch, so a visitor's live session joins it.
- `GET /api/demo` returns `{enabled, replayReady}`. The dashboard shows a Play prepared run button while `replayReady` is true.

Manifest returned by reset:
```json
{
  "project": {"title": "Offer letters"},
  "files": [{"path": "Inbox/Offer letter template.docx", "base64": "..."}],
  "chats": [{"title": "...", "sessionId": "<uuid>", "jsonl": "<Pi session JSONL>"}]
}
```
Paths inside `jsonl` use the placeholder `{{WORKSPACE}}` for the project folder.
`chats` is in chronological order. A chat with two user turns is one session.

### Demo mode in t3code (patch 0003)
Enabled when the server starts with `HONE_DEMO=1`.
- A demo seeder resets on server start and on a Reset demo button in the sidebar.
  It calls Hone's reset, force deletes the previous demo project, rewrites the project folder, writes each Pi session file under a fresh name, creates the project with Pi as its default model, and writes each chat as native t3code events through `EventSinkV2`.
  Open browsers update live, and the browser stays signed in.
- Seeded replies carry their Pi provider thread, so the rating control works and shows the feedback Hone already holds.
- The input files are dragged from the existing Files panel into the composer.
- A Hone button next to Settings, Usage and Pull requests opens the Hone dashboard inside t3code.

### Booth checks
1. After a reset, t3code shows the prepared chats. Each opens with its tool calls, replies, output documents and feedback.
2. Dragging the template and the new approval into a new chat runs the live agent, which writes the letter. Thumbs down reaches Hone and fills the batch.
3. Play prepared run animates the run, and the new version appears in Versions.
4. Reset demo brings both apps back to the prepared state with no command line. Restarting t3code does the same.
5. Start optimization still runs the real pipeline.
