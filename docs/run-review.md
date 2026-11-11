# Reviewing a run before it is cached or filmed

A real MAJICS run is replayed from the cache every time someone presses Start optimization on the same input, and it appears in the booth videos.
So a run is cached, shipped or filmed only after it passes this review. A run that fails is recorded again.

## Who reviews

Two independent reviewers who did not record the run read its artifacts: the events, the review report, the review JSON, the proposals, the fused proposal, the verifier verdict, the AGENTS.md diff and the commit message, together with the batch traces and their feedback.
A run passes when both reviewers pass it. Their notes are kept with the cache entry.

## What a run must show

1. **Clean execution.** Every seat finishes. No error, no timeout, no empty answer, no retry visible in the feed. Every follow-up the judge asked was answered.
2. **Grounded review.** Each finding cites the traces it comes from, and those traces really show it. The report names what the feedback asked for and does not invent problems.
3. **Real cross-examination.** The judge's questions target an actual disagreement or a gap, and the answers resolve it. Questions that only repeat the task do not count.
4. **Right edits.** Each AGENTS.md edit follows from evidence in the batch, is general enough to help the next session, and is specific enough to act on. One off requests stay out. Nothing the evidence does not support is added. Edits do not contradict existing rules unless they replace them on purpose.
5. **Clear commit.** The title says what changed in plain words, and the body says why, citing the sessions.
6. **Presentable.** Read on the run page and the Versions page, the run tells a story a visitor can follow. No garbled text, no leaked secrets or local paths that mean nothing to a visitor, no rambling.

## Outcome

- Pass. The entry is marked approved with both reviewers' notes and the date, and only then can it be replayed, shipped or filmed.
- Fail. The notes say which point failed. The run is recorded again, after changing the input, the roster or the reasoning level if the same failure would repeat.
