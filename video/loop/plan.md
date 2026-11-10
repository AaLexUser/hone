# Booth video loop

A silent landscape loop (1920 by 1080, 30 fps) that plays on a screen at the booth while visitors walk past.
It cycles through short scenarios. Each one is a complete story a visitor can catch from any point within about a minute.
Every scenario is real footage of the booth stack, built with the same tooling as `video/` (captions, zooms, time lapse badges with real durations).

## Shape of the loop

- Each scenario opens with a two second chip naming it, plays 45 to 75 seconds, and ends on its outcome.
- A short results card from Table I of the paper sits between cycles.
- The loop ends on a frame that cuts cleanly back to the first one.
- Deliverables are one MP4 for any player set to repeat, and `loop.html` that plays it full screen, muted and looping in a browser.

## Scenarios

| # | Name | Domain and files | What happens | What it shows about Hone |
|---|---|---|---|---|
| 1 | A complaint becomes a rule | Offer letters, hiring approval PDF and DOCX template | The agent prints a £0 bonus row, thumbs down, a real MAJICS run adds a rule, the next letter is right | The core loop, feedback to AGENTS.md without re-running anything |
| 2 | A one off stays one off | Offer letters | One session gets a request scoped to a single candidate, another gets a general complaint. The judge cross-examines the panel | Hone keeps a scoped request out of AGENTS.md and turns only the general complaint into a rule |
| 3 | Nothing wrong, nothing changes | Offer letters | A batch where every session is approved | A real run ends with no changes, so Hone does not churn the file |
| 4 | Spreadsheets | Monthly expense report, receipts as PDF, an XLSX template | Feedback about the company's number format and a frozen header row turns into a rule, the next report follows it | Hone works across office tasks, not just one demo |
| 5 | Meeting minutes | A meeting transcript and a DOCX minutes template | Feedback asks for action items first, each with an owner and a date. The rule lands and the next minutes follow it | Preferences, not only errors, become rules |
| 6 | Every change is a version | The Versions page | Compare two versions, branch from an older one, set a version as current, the t3code chip shows the new version | AGENTS.md history is in Git and nothing is lost |

## Honesty rules

- Real chats, real feedback, real MAJICS runs. Time lapse badges show each run's real duration.
- If a real run does something other than the plan, the clip shows what it did, and the caption says so plainly.
- Captions follow `video/script.md`. Sentence case, no colons, semicolons or dashes, Hone indigo for the key word.
