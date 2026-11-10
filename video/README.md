# Hone demo video

A landscape screen recording of the booth stack, 1920 by 1080 at 30 fps, with burned in captions. `script.md` holds the scenes, captions and the facts they must keep.

## Rebuild from captured footage

```sh
sh video/build.sh <footage dir> <out dir>
```

This writes `hone-demo.mp4`, `hone-demo.srt` and `contact-sheet.png` (one frame per second) to the out dir. It needs Python 3 with Pillow, ffmpeg with libx264, and Node with Playwright (`PLAYWRIGHT` points at the package, default `/opt/node-tools/node_modules/playwright`).

## Files

- `timeline.json` is the edit. Each shot names a clip, a start and end mark from the capture log, a speed or a duration, camera keyframes, highlight boxes and captions. Cards have no clip. Positions are CSS pixels of the 1920 by 1080 page. In a caption, `/` breaks the line and `*word*` sets the key word in Hone indigo. `{speed}` in a badge becomes the shot's real speed up.
- `compose.py` resolves the timeline against the capture logs, crops and scales every footage frame, composites the overlay and encodes the MP4. It also writes the SRT.
- `overlay.html` draws the captions, highlight boxes, cursor, time lapse badge and the title, result and end cards for one frame. Colours are the tokens from `apps/web/src/index.css`, fonts come from `poster/assets/fonts`.
- `render_overlay.cjs` renders every distinct overlay state through `overlay.html` to a transparent PNG.
- `capture/` records the footage.

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
