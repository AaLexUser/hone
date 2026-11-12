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
3. Optimization. The presenter presses Start optimization. A real run takes about ten minutes.
   When Hone holds an approved recording of a real run on exactly this batch, it replays that run through its own code in about a minute and a half instead.
   The run page shows the reviewers, the judge questioning them, the proposers and the verifier either way.
4. Commit. The Versions page shows the new AGENTS.md version with its diff.
5. For visitors who stay, earlier runs show the cross examination at work.
   Hone held back an edit no feedback supported, refused to turn a one off request into a rule, and changed nothing when nothing was wrong.

## Verified in the development container on 9 November

- After a reset, t3code lists the 13 prepared chats under Offer letters, each with its tool calls, replies and documents.
- A new message in a prepared chat resumes the same Pi session, and the live agent answered from the letter.
- A new chat with `Inbox/Hiring approval Amara Osei.pdf` and `Inbox/Offer letter template.docx` dragged into the composer produced `Offer_Osei_Amara.docx` and `.pdf`.
  The live letter printed `Sign-on Bonus £0` and `Equity Grant 0 shares`, so the visitor's complaint matches the prepared run.
- Thumbs down reached Hone and filled the batch to 4 of 4.
- Reset demo restored both apps to the prepared state, removed the visitor's chat and files, and cleared an unsent draft.

## Still open before the booth

- The visitor's turn is recorded in `clients/t3code/turn-cache/` and stays valid while the model, the request and the project files stay the same.
  The approved optimization recording is run r_89a9, shipped as `packages/hone/demo/run-cache/20261112T053232-r_89a9.json`. One reviewer passed it on all six points, the other failed point 4 because the rule's condition also reads on a blank field, and the author approved it on 12 November because the condition follows the feedback's own words.
  A replay check with only the shipped copies played the visitor's chat in 208 seconds and the optimization in 91 seconds, ending with the same rule in Versions.
  Both recordings match only on the current MAJICS and verifier code, the roster in `deploy/hone.yaml`, `HONE_DEMO_DATE=2026-11-11` and the same Pi model. Change none of them before the booth, or the visit runs live.
- Run the guided visit once on the laptop's own stack before the trip to confirm both replays there.
- PDF preview inside t3code could not be checked under headless Chromium here. DOCX preview works. Check a PDF in the laptop's Chrome.
- If the conference Wi-Fi fails, the live agent cannot reach its model. Show the prepared chats and a replayed run, which needs no network, and keep the recorded loop as a backup.
- Rotate the OpenCode key after the conference.

## Laptop checklist

1. Install LibreOffice with `soffice` on PATH, poppler for `pdftotext`, and python-docx for the agent's Python.
2. Build t3code with patches 0001 to 0003 as `clients/t3code/README.md` describes, and link the Pi extension.
3. Start Hone with `HONE_DEMO=1` and its own empty `HONE_DATA_DIR`, bound to 127.0.0.1. Hone refuses a demo reset on a folder with real history. Set `HONE_DEMO_DATE=2026-11-11` so the prepared state matches the recorded runs. The first start builds the prepared state in about 20 seconds.
4. Start the t3code server with `HONE_DEMO=1`, `HONE_URL`, `HONE_TOKEN`, `HONE_DASHBOARD_URL` and `HONE_DEMO_DIR` set to a new empty folder. It seeds the chats on start.
5. Pair the browser once, open the Offer letters project, and run one full visitor loop, then press Reset demo.

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
- `POST /api/demo/reset` (write token) restores the prepared state for today's date, or for `HONE_DEMO_DATE` when it is set, and returns the manifest below.
  Hone builds the prepared data dir once per day in a child process and caches it, and a reset copies the cache over the live data dir and reopens it.
  Open dashboards reload on a `demo_reset` bus event.
- A reset keeps the run cache (`<data dir>/run-cache/`), so recorded runs of the prepared batch survive it.
- `GET /api/demo` returns `{enabled}`.
- Building the prepared state runs `pdftotext` and LibreOffice (`soffice`), so the laptop needs poppler and LibreOffice, which the live agent needs anyway.
  `uv run python -m hone.demo build --out <dir>` writes the same state into a folder for inspection.

Manifest returned by reset:
```json
{
  "project": {"title": "Offer letters"},
  "files": [{"path": "Inbox/Offer letter template.docx", "base64": "..."}],
  "chats": [{"title": "...", "sessionId": "<uuid>", "jsonl": "<Pi session JSONL>"}]
}
```
Paths inside `jsonl` use the placeholder `{{WORKSPACE}}` for the project folder.
Reset takes an optional JSON body `{"workspace": "<absolute project folder>"}`. Hone then puts that folder in place of the placeholder in its own copy of the sessions, so its trace pages show the real paths.
`chats` is in chronological order. A chat with two user turns is one session.

### Run cache
Start optimization looks up the frozen batch in the run cache before it starts Harbor (`packages/hone/runcache.py`).
The cache is on only in demo mode (`HONE_DEMO=1`). Otherwise every run is real and nothing is recorded.
- Every real run that ends with a commit or with no changes is stored as a candidate entry under the fingerprint of its input, with the verdict of each attempt.
- A candidate replays only after two reviewers pass it as `docs/run-review.md` describes. Their notes and the date are kept with the entry.
- On a hit, Hone replays the recorded driver events and artifacts through its own run loop, compressed to about a minute and a half, then verifies and commits the proposal as for any run.
  Before it picks an entry, Hone runs the current verifier over every recorded attempt. If any attempt would get a verdict other than the recorded one, the run is real.
- A cache file that cannot be read or has the wrong shape is skipped with a log line. If the lookup fails anyway, the run is real and is not recorded.
- Nothing on the page says that a run was replayed. `GET /api/runs/<id>` has `replayOf` with the entry id, the source run id, the recording date and the review.
- The input is a batch of exact traces. A visitor's live session in the batch, or a changed feedback, makes the run real.

The fingerprint is the SHA-256 of one canonical JSON document with these parts.
- Each batch trace in batch order, its session JSONL and its feedback.
- The base AGENTS.md text and its version.
- The experience log as the sandbox sees it.
- The MAJICS configuration, which is the providers, models, seats and reasoning levels, and the retry and timeout limits.
- A hash of the code that shapes a run, which is `packages/hone/majics/` with the prompts and the driver, and the verifier in `packages/hone/patch.py`. A change there makes every older recording miss.

Before hashing, every value that differs between two copies of the same input becomes a numbered placeholder.
These are UUIDs, trace ids, commit hashes, each session's working folder, ISO times and dates, millisecond timestamps under a `timestamp` or `at` key, Python `date(...)` literals, and dates written out in English.
Each date format is its own kind, so `17 November 2026` never matches `November 17, 2026`.
A date's placeholder keeps its offset in days from the first date in the document, and a time keeps its time of day. A batch therefore matches only when all of its dates move by the same number of days.
On a hit, each recorded value maps to the current one, as a whole token, in every replayed event and artifact, and the recorded run id maps to the new one.

The prepared scenario does not move by whole days from one booth day to the next.
Start dates fall on the following Monday, and the base AGENTS.md names a fixed example date, so the scenarios built for 14 November, 17 November and 1 December have three fingerprints.
Record on the scenario of the recording day. `HONE_DEMO_DATE=2026-11-11` makes Hone build the prepared state for that day whatever the clock says. Set it on the stack that records and on the booth stack.
The recorded visitor turn keeps the clock of the day it was recorded, so the demo date must be that day. Otherwise the visitor's letter is dated before the approval it was written from, and the run argues about the dates instead of the feedback.

Entries live in two places.
- `<data dir>/run-cache/`, written by Hone. It survives restarts and demo resets.
- `packages/hone/demo/run-cache/`, shipped with the code and read only. A fresh booth stack replays these from the first start. A local entry with the same id wins.

The dev endpoints need demo mode and the write token.
- `GET /api/run-cache` lists entries, newest first, with their review status.
- `GET /api/run-cache/<id>` returns one entry. Save the body as `packages/hone/demo/run-cache/<id>.json` to ship it.
- `POST /api/run-cache/<id>/review` with `{"status": "approved", "notes": ["...", "..."]}` records the verdict. `rejected` and `candidate` work the same way. Approving needs notes.

A shipped entry replays only on a stack with the same MAJICS configuration, the same MAJICS and verifier code, and the same scenario day, because all three are part of the fingerprint.

### Demo mode in t3code (patch 0003)
Enabled when the server starts with `HONE_DEMO=1`.
- A demo seeder resets on server start and on a Reset demo button in the sidebar.
  It calls Hone's reset, force deletes the previous demo project, rewrites the project folder, writes each Pi session file under a fresh name, creates the project with Pi as its default model, and writes each chat as native t3code events through `EventSinkV2`.
  Open browsers update live, and the browser stays signed in.
- Seeded replies carry their Pi provider thread, so the rating control works and shows the feedback Hone already holds.
- The input files are dragged from the existing Files panel into the composer.
- A Hone button next to Settings, Usage and Pull requests opens the Hone dashboard inside t3code.

### Guide mode (patches 0008 and 0009)
Guide mode lets a visitor walk through the demo alone, with no presenter. `clients/t3code/README.md` lists the steps and settings.
- The presenter turns it on with the Guide button in the sidebar. Leaving it takes a two second hold and the PIN in `HONE_GUIDE_PIN`.
- After `HONE_GUIDE_IDLE_VIDEO_SECONDS` without a touch the booth video plays. After `HONE_GUIDE_IDLE_RESET_SECONDS` the guide resets the demo and shows the welcome card.
- The guide writes the visitor's request and feedback word for word as the recorded chat and run had them. The agent turn cache then replays the recorded chat, Hone gets the same trace, and Start optimization finds the approved run in the run cache.
- The visitor's chat replays in about two minutes, and the optimization in about a minute and a half.

### Recording the guided visit
Two recordings make the guided visit quick. Both come from real runs on the compose stack, on the scenario of the booth day.
1. Build the stack with every patch. Set `HONE_TURN_CACHE_RECORD=1` in `deploy/.env` and run `docker compose up -d --build t3code`. The restart resets the demo.
2. Open the site, press Guide in the sidebar and follow the guide to the end. Send the request as written and the feedback as written.
   The real Pi agent answers, and `hone-pi` records the turn in the `turn-cache` volume.
   Start optimization runs the real MAJICS pipeline on the three prepared sessions and the new one, and Hone keeps it as a candidate run.
3. Check that the letter prints the £0 bonus and 0 shares rows the feedback names. If it does not, delete the new file in the `turn-cache` volume, reset the demo and repeat step 2.
4. Have two reviewers pass the run as `docs/run-review.md` describes, record the verdict with `POST /api/run-cache/<id>/review`, and save `GET /api/run-cache/<id>` as `packages/hone/demo/run-cache/<id>.json`.
5. Copy the recording from the volume into `clients/t3code/turn-cache/`, for example with `docker compose cp t3code:/home/node/turn-cache/. ../clients/t3code/turn-cache/`.
6. Set `HONE_TURN_CACHE_RECORD=0`, rebuild t3code and Hone, and walk the guide once more. The chat should replay, and the run should take about a minute and a half.

A changed model, thinking level, AGENTS.md, request text, scenario day, set of project files, or a changed Inbox file the request links to makes the turn run live. A changed feedback, roster or MAJICS code makes the run real.

### Booth checks
1. After a reset, t3code shows the prepared chats. Each opens with its tool calls, replies, output documents and feedback.
2. Dragging the template and the new approval into a new chat runs the live agent, which writes the letter. Thumbs down reaches Hone and fills the batch.
3. Start optimization on the prepared batch replays the approved recording in about a minute and a half, and the new version appears in Versions.
4. Reset demo brings both apps back to the prepared state with no command line. Restarting t3code does the same.
5. Start optimization on any other batch runs the real pipeline.
