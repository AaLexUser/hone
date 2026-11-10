# Hone demo video

A landscape screen recording of the booth stack, 1920 by 1080 at 30 fps, with burned in captions. `script.md` holds the scenes, captions and the facts they must keep.

## Rebuild from captured footage

```sh
sh video/build.sh <footage dir> <out dir>
```

This writes `hone-demo.mp4`, `hone-demo.srt` and `contact-sheet.png` (one frame per second) to the out dir. It needs Python 3 with Pillow, ffmpeg with libx264, and Node with Playwright (`PLAYWRIGHT` points at the package, default `/opt/node-tools/node_modules/playwright`).

## Files

- `timeline.json` is the edit of the demo video. Each shot names a clip, a start and end mark from the capture log, a speed or a duration, camera keyframes, highlight boxes and captions. Cards have no clip. Positions are CSS pixels of the 1920 by 1080 page. In a caption, `/` breaks the line and `*word*` sets the key word in Hone indigo. `{speed}` in a badge becomes the shot's real speed up.
- `compose.py` resolves a timeline against the capture logs, crops and scales every footage frame, composites the overlay and encodes the MP4. It also writes the SRT. Run it as `python3 compose.py <timeline> <footage dir> <out.mp4>`. A shot with `video` instead of `clip` plays a rendered 1920 by 1080 video as it is.
- `overlay.html` draws the captions, highlight boxes, cursor, time lapse badge and the title, result, end and scenario chip cards for one frame. Colours are the tokens from `apps/web/src/index.css`, fonts come from `poster/assets/fonts`.
- `render_overlay.cjs` renders every distinct overlay state through `overlay.html` to a transparent PNG.
- `contact_sheet.sh` writes one frame per second of a video, ten to a row, for review.
- `capture/` records the footage of the demo video. `rig.cjs` and `flows.cjs` are shared with the loop's capture scripts.
- `loop/` builds the booth loop, see below.

## Capture the footage

The capture drives a headful Chromium on an Xvfb display at 1920 by 1080 CSS pixels and device scale 1.5, and records the screen with ffmpeg x11grab at 2880 by 1620. Each recording keeps wall clock timestamps, and the driver logs marks and cursor moves on the same clock, so the composer can draw the cursor and cut on marks.

```sh
Xvfb :99 -screen 0 2880x1620x24 -nolisten tcp &
cd video/capture
DISPLAY=:99 node record.cjs chat <footage dir>    # reset, live chat, thumbs down, the real MAJICS run (about 15 minutes)
DISPLAY=:99 node record.cjs review <footage dir>  # the finished run's Activity feed and the Versions page
DISPLAY=:99 node record.cjs chat2 <footage dir>   # a new chat with the same approval, after the commit
DISPLAY=:99 node record.cjs reset <footage dir>   # Reset demo, back to the prepared state
```

The booth stack must be up at `BOOTH_URL` (default `http://127.0.0.1:8443`) with the booth login in `BOOTH_USER` and `BOOTH_PASS`. A new take has new marks and a new run, so check the shot ranges, the badge durations and the highlight boxes in `timeline.json` against its contact sheet before you publish it. The `review` stage logs the boxes of the Activity rows and the new AGENTS.md line in `review.json`.

## Booth loop

The booth screen plays a silent loop of short scenarios. `loop/plan.md` lists them. Each scenario has a folder `loop/<scenario>/` with its `timeline.json` and, when it needs new footage, a `capture.cjs`. Its footage and rendered clip live in a work dir outside the repo, at `<work dir>/<scenario>/footage` and `<work dir>/<scenario>/<scenario>.mp4`.

```sh
python3 video/loop/build.py clip 4-spreadsheets <work dir>   # one scenario's clip and contact sheet
python3 video/loop/build.py loop <work dir>                  # every rendered clip, in loop.json order
```

The loop command writes `<work dir>/hone-loop.mp4`, its contact sheet and `loop.html`. The Hone title card opens the cycle, each clip follows a three second chip with the scenario's name from `loop.json`, and the Table I results card closes the cycle. The results card ends on the bare background the title card fades in over, so the cut back to the start is clean. Pace a clip so a visitor can follow it. A caption stays long enough to read twice, a time lapse runs at about 15 to 20 times where the screen changes, and each outcome holds for several seconds. A scenario with no rendered clip is left out, so a new scenario needs only its capture, its timeline and a line in `loop.json`. Once a clip is rendered and checked, its raw footage can go.

`loop.html` plays `hone-loop.mp4` from its own folder, muted and looping, with no controls, and starts again by itself after a reload or a stall. A click or a key press makes it full screen. For a kiosk, open it with `chromium --kiosk --autoplay-policy=no-user-gesture-required file://<work dir>/loop.html`.

These scenarios exist so far.

- `1-complaint` re-cuts the demo video's footage (`capture/record.cjs`), so its footage dir is that one.
- `4-spreadsheets` runs on a second booth stack with demo mode off and fresh volumes. `make_files.py` writes the project's office files, and `capture.cjs` drives the chats, the feedback and the real run. The booth image has no openpyxl, so this stack's t3code image adds `python3-openpyxl` on top. The stack mounts the demo stack's `docker-lib` volume to reuse the sandbox image, so the demo stack's `docker` service stays stopped while it runs. Batch size 3, set with `POST /hone/api/config`.
- `6-versions` runs on the demo stack and ends with Reset demo.
