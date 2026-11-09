# Real UI screenshots

These scripts produced the screenshots in `assets/stills/real/`.

1. Serve a copy of the demo data (`scripts/dev/seed_runs.py seed`) with Hone on port 8095. Mark the last three traces `new` and set `batch_size` to 3, so the dashboard shows a ready batch.
2. Start t3code with `HONE_URL=http://127.0.0.1:8095`. Run `node t3pair.cjs <outdir> <pairing token>`, then `node t3fb.cjs <outdir>` for the feedback popover.
3. Run `node full4.cjs <outdir>` and `node commit.cjs <outdir>` to shoot the dashboard, run and versions pages at 4x. The crops used are in the poster commit history.
