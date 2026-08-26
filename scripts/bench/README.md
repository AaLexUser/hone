# Generic Harbor benchmark runner for Hone

Reusable scripts to run the Hone self-improvement loop on any local Harbor
dataset and compare against a baseline.

## Layout

- `split_batches.py` — split a Harbor dataset dir into training batches + the
  final full run (deterministic sample for train, complete original dataset
  for final).
- `run_experiment.py` — the orchestrator: per batch, runs Harbor trials with
  the pi agent and the hone extension inside the sandbox (current `AGENTS.md`
  bind-mounted at `/workspace/AGENTS.md`, extension syncs it from the service
  at session start), converts each trial's downloaded pi log into a hone
  trace, posts per-task feedback (`Correct Answer` /
  `Expected: … Got: …`), triggers the Hone optimizer, waits for the new
  `AGENTS.md` version, then moves to the next batch. After the last batch it
  can run the full dataset once and compare exact-match against a baseline
  trials directory.

## Quick start

```bash
# 1. one-time: generate the dataset (officeqa example)
cd harbor-officeqa-offline-adapter/adapters/officeqa-offline && uv sync && cd ..
uv run --project adapters/officeqa-offline officeqa-offline   # writes datasets/officeqa-offline

# 2. create an experiment (splits + config)
uv run python scripts/bench/run_experiment.py init \
    --exp experiments/run1 \
    --dataset harbor-officeqa-offline-adapter/datasets/officeqa-offline \
    --train-count 24 --batch-size 8 \
    --baseline pi-gpt-5.4-mini-baseline

# 3. training batches + optimization (resumable; rerun skips finished batches)
uv run python scripts/bench/run_experiment.py batches --exp experiments/run1

# 4. final full-dataset run + baseline comparison
uv run python scripts/bench/run_experiment.py final --exp experiments/run1
```

## Experiment directory

```
experiments/run1/
  config.json           # model, concurrency, baseline path, timeouts
  splits/manifest.json  # batch task lists + final task list (single source of truth)
  pi-config/            # files bind-mounted into every sandbox
    models.json         # provider -> gateway (from .env)
    hone.json           # service URL/token (rewritten to host.docker.internal)
    extensions/hone.ts  # the hone client extension
  agents-md/<ver>.md    # snapshot of AGENTS.md used per batch/final
  batch_XX/job.yaml     # harbor JobConfig
  batch_XX/jobs/…       # harbor trial artifacts (agent/pi.txt, verifier/…)
  batch_XX/report.json  # per-task reward + feedback + trace ids
  batches-summary.json  # score + optimizer status per batch
  final/report.json     # full-dataset run
  final-summary.json    # final vs baseline comparison (paired, per-task)
  hone-data/            # the hone service state (sqlite, traces, runs)
  service.json/log      # service endpoint/pid + stdout
```

## Proving AGENTS.md reached the model

pi injects `AGENTS.md` into the **system prompt** (it never appears in the
session/trace files, which record only the conversation). To make this
auditable, every sandbox also loads `pi-extensions/dump-system-prompt.ts`,
which writes the fully assembled system prompt to `/logs/agent/system-prompt.txt`;
harbor collects it per trial as `<trial>/agent/system-prompt.txt`. Grep it for
the current AGENTS.md rule text to confirm what the model actually saw.

Local one-off check:

```bash
cd dir-with-AGENTS.md
PI_SYSTEM_PROMPT_FILE=./system-prompt.txt pi --print --no-session \
    -e scripts/bench/pi-extensions/dump-system-prompt.ts \
    --provider openai --model gpt-5.4-mini "Reply with exactly one word: ready"
```

## Options worth knowing

- `batches --only-batch N`, `--limit-batches N`, `--limit-tasks N` — pilot
  runs on a small slice before committing to the full loop.
- `batches --no-optimize` — collect traces without running the optimizer.
- `final --limit-tasks N` — smoke-test the final harness.
- `--force` — rerun a stage whose report already exists.
- `--keep-service` — leave the hone API running between invocations (the
  runner attaches to it automatically via `service.json`).
- Any stage is safe to re-invoke: finished batches are skipped, the service
  is reattached or restarted, and the final run reuses the last `AGENTS.md`.

## Scoring

Reward is the benchmark verifier's own metric (OfficeQA: exact match, reward
1.0). The final comparison is paired per task against the baseline trials
dir (`*/result.json`), including `flipped_up` / `flipped_down` task lists in
`final-summary.json`.
