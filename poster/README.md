# Hone ICDM 2026 demo poster

The poster is 90 by 120 cm, portrait. `index.html` is self-contained, with fonts, the ICDM logo, the code QR and the screenshots in `assets/`.

- `out/hone-poster.pdf` is the print file, 900 by 1200 mm, with embedded fonts.
- `out/preview.png` is a screen preview.

## Fill in before printing

Search `index.html` for `placeholder`. The only one left is the Paper ID in the bottom right corner.

## Rebuilding

`tools/` holds the sources that `index.html` is built from (`body.html`, `body.css`, `diagram.svg`, `build.py`). `tools/go.sh` rebuilds `index.html` and renders `out/`. It overwrites `index.html`, so edit the files in `tools/` if you rebuild. `tools/audit.cjs` checks the smallest text size, contrast, banned words and banned punctuation. `tools/stageshow/` holds the sources of the five UI stills.

Rendering needs Node with Playwright and Python 3.
