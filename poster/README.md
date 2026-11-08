# Hone · ICDM 2026 demo poster

90 × 120 cm portrait. `index.html` is self-contained (fonts and images in `assets/`); open it in Chromium and print, or use the ready files in `out/`:

- `out/hone-poster.pdf`: print file, 900 × 1200 mm, fonts embedded
- `out/preview.png`: screen preview

## Fill in before printing

Search `index.html` for `placeholder`: affiliations, email, institution logos, acknowledgment line, Paper ID (bottom right).

## Rebuilding

`tools/` holds the sources `index.html` is generated from (`body.html`, `body.css`, `diagram.svg`, `build.py`). `tools/go.sh` rebuilds `index.html` and renders `out/`; it overwrites `index.html`, so make edits in `tools/` if you rebuild. `tools/audit.cjs` checks minimum text size, contrast and banned words. `tools/stageshow/` holds the sources of the three UI stills.

Rendering needs Node with Playwright and Python 3.
