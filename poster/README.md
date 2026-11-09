# Hone ICDM 2026 demo poster

The poster is 90 by 120 cm, portrait. `index.html` is self-contained, with fonts, the ITMO logo, the code QR and the screenshots in `assets/`.

- `hone-poster.pdf` is the final print file, 900 by 1200 mm, one page, with embedded fonts.
- `tools/go.sh` writes a fresh `out/hone-poster.pdf` and `out/preview.png` (not committed). Copy the PDF here after a rebuild.

## Fill in before printing

All placeholders are filled in.

## Rebuilding

`tools/` holds the sources that `index.html` is built from (`body.html`, `body.css`, `diagram.svg`, `build.py`). `tools/go.sh` rebuilds `index.html` and renders `out/`. It overwrites `index.html`, so edit the files in `tools/` if you rebuild. `tools/audit.cjs` checks the smallest text size, contrast, banned words and banned punctuation. `tools/stageshow/` holds the sources of the five UI stills.

Rendering needs Node with Playwright and Python 3.
