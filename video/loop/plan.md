# Booth video loop

A silent landscape loop (1920 by 1080, 30 fps) that plays on a screen at the booth while visitors walk past.
It cycles through scenarios. Each one is a complete story, paced so a visitor can follow it without effort.
Every scenario is real footage of the booth stack, built with the same tooling as `video/` (captions, zooms, time lapse badges with real durations).

## Shape of the loop

- The Hone title card opens each cycle, and a short results card from Table I of the paper closes it. No clip has a title, results or end card of its own.
- Each scenario opens with a three second chip naming it, then plays its clip and ends on its outcome.
- Clips run about one to two and a half minutes. A caption stays long enough to read twice, time lapses slow down where the screen changes meaningfully, zooms are slow, and each outcome holds on screen.
- The loop ends on a frame that cuts cleanly back to the first one.
- Deliverables are one MP4 for any player set to repeat, and `loop.html` that plays it full screen, muted and looping in a browser.

## Scenarios

`loop.json` lists every clip in loop order, and `build.py` skips a clip whose folder does not exist yet.
The council's picks and the reasons are in `council.md`.

| Folder | Name | State |
|---|---|---|
| 1-complaint | A complaint becomes a rule, offer letters | Built from the approved booth run r_89a9 and its recorded visitor turn |
| 4-spreadsheets | Spreadsheets too, expense reports | Built on an older roster |
| 7-singles-day | A sale in the right time zone | Built from approved run r_3db5 |
| 8-ohio | Ohio is not in Oxford | Built from approved run r_3931 |
| 10-badges | Every name on one line | Built from approved run r_a466, ends on the before and after sheets |
| 6-versions | Every change is a version | Built |
| not planned | Don't invent our results, "Not useful" | The loop has enough scenarios. Transcripts was dropped because the agent anonymised every name unprompted |

Every clip uses a real run that two reviewers passed under `docs/run-review.md`.

## Honesty rules

- Real chats, real feedback, real MAJICS runs. Time lapse badges show each run's real duration.
- If a real run does something other than the plan, the clip shows what it did, and the caption says so plainly.
- Captions follow `video/script.md`. Sentence case, no colons, semicolons or dashes, Hone indigo for the key word.
