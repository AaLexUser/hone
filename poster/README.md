# Hone · ICDM 2026 demo poster

90 × 120 cm portrait. `index.html` is self-contained (fonts, ICDM logo and code QR in `assets/`).

- `out/hone-poster.pdf`: print file, 900 × 1200 mm, fonts embedded
- `out/preview.png`: screen preview

## Fill in before printing

Search `index.html` for `placeholder`: affiliations, email, institution logos, acknowledgment, Paper ID (bottom right).

## Rendering

`node render.cjs` (needs Node with Playwright) rewrites `out/preview.png` and `out/hone-poster.pdf` and reports text smaller than 8.5 mm or anything overflowing the page.
