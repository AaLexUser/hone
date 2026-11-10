# Council decision on the loop scenarios

Five brainstorm agents proposed 35 scenarios (office documents, data work, Hone's judgment, teams and time, visual payoff).
Three independent judges scored all of them on Hone uniqueness, instant read, reliability, audience fit and set fit.
One judged as a booth communicator, one as the paper's reviewer checking claims against the code, one as the producer.

## Chosen, in recording order

| # | Scenario | Votes | Hone behaviour | Main risk and mitigation |
|---|---|---|---|---|
| 1 | Singles' Day in the wrong time zone. A shop's daily orders from a UTC export put the busiest hour on 10 November, the day before the sale | All three | A plain complaint becomes a rule, which carries over to a new question (hourly orders) in the next session | Low. The export gives no time zone, so the mistake is near certain. Keep "Singles' Day" out of the request and file names |
| 2 | Ohio is not in Oxford. AGENTS.md says British spelling, two US clients complain, a UK client praises | All three | Conflicting feedback. Hone narrows an existing rule by client country with a replace edit instead of flipping it | The run may flip the rule. Two takes, then fall back to "We changed our name" |
| 3 | Anonymised interview transcripts. Names survive in a table, the page header and short forms | Two picks, one alternate | A general rule with a self check (search the PDF for each original name), and a request for one interview only that stays out | The one off could still become a scoped line. Show what the run did |
| 4 | Workshop name badges. Long names wrap or get cut, the last row spills onto page 2 | Two picks | A rule with a check the agent can run itself. Reads with no words | The session after the fix must settle. Test it twice first |
| 5 | Don't invent our results. Rebuttal drafts with made up experiment numbers, plus "for this paper put Reviewer 2 first" | One pick, one alternate | Invented numbers become a [TODO result] rule, the paper specific order stays out | Pick reviews that ask for several new experiments so the agent invents numbers |
| 6 | "Not useful". The only feedback is two words, the user's next message says what was missing | One pick, one alternate | Hone reads the whole trace, not only the feedback, to interpret vague feedback | The judge's reading must show in the real activity log |

Alternates are the duplicate deal (the CSV must be small enough that the agent prints every row, because reviewers see only traces) and the churn driver leak.

The expense report already recorded in batch one is kept only if its clip reads at a glance. No judge picked it.

## Rules the judges set from the code

- Reviewers and proposers see only the session traces, `agents.md`, `evidence.json`, `batch.json` and `log_edits.json`, never the Inbox files. Any evidence must appear in the chat itself.
- The verifier checks anchors, trace ids, edit count and the commit message. It does not judge whether an edit is supported. Holding back is the judges' job, and it is not reliable because reviewers also report tool waste and unsupported claims without feedback. Captions never promise a held back edit. Unconfirmed points are "left unresolved".
- A run with no edits makes no commit. It shows No changes on the Runs page, not on Versions. A clean batch is not guaranteed to end with no change.
- A request scoped to one client can legitimately become a client specific line. Captions describe what the run did.
- Captions quote or paraphrase the real activity log only. The judge's questions in the brainstorm files are predictions.
- Every seat in the booth stack runs DeepSeek V4.1 Flash, so captions never say "different models".
- Hone does not know people. Names live only in chat titles and captions.
- Each scenario gets its own Hone data directory with batch size 4, so batches and `log_edits.json` never mix across clips.
- Cap each scenario at two takes before its fallback. Delete each scenario's Hone volume once its clip is cut.

Full verdicts and the idea pool are kept outside the repository with the brainstorm files.
