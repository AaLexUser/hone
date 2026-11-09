Real-UI screenshots for the user-story band (`assets/stills/real/`).

1. Serve a copy of the demo data (`scripts/dev/seed_runs.py seed`) with Hone on port 8095; mark the last three traces `new` and set `batch_size` to 3 so the dashboard shows a ready batch.
2. Start t3code with `HONE_URL=http://127.0.0.1:8095`, then `node t3pair.cjs <outdir> <pairing token>` and `node t3fb.cjs <outdir>` (feedback popover).
3. `node full4.cjs <outdir>` and `node commit.cjs <outdir>` shoot the dashboard, run and versions pages at 4x; the crops used are in the poster commit history.
