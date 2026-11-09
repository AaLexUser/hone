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
