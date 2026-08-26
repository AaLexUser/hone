"""Split a Harbor dataset into training batches plus the final full run.

Works on any local Harbor dataset directory (a folder of per-task dirs, each
with a ``task.toml``). The output is a single ``manifest.json`` consumed by
``run_experiment.py`` — the one source of truth for batch composition:

    splits/manifest.json    # dataset, seed, sizes, batch task lists, final list

The train pool is a deterministic random sample of the dataset; the final run
is always the complete original dataset, so scores stay comparable across
experiments.

Usage:
    python split_batches.py --dataset datasets/officeqa-offline \
        --out splits --train-count 24 --batch-size 8 [--seed 42]

    # or split by ratio instead of count
    python split_batches.py --dataset ... --out splits --train-ratio 0.1 --batch-size 8
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def discover_tasks(dataset_dir: Path) -> list[Path]:
    """Task dirs in deterministic (sorted) order — the canonical dataset order."""
    tasks = [
        p
        for p in sorted(dataset_dir.iterdir())
        if p.is_dir() and (p / "task.toml").is_file()
    ]
    if not tasks:
        raise SystemExit(f"no harbor tasks found under {dataset_dir}")
    return tasks


def build_manifest(dataset_dir: Path, *, train_count: int | None, train_ratio: float | None,
                   batch_size: int, seed: int) -> dict:
    """Build the splits manifest: deterministic train sample + full final run."""
    if train_count is None and train_ratio is None:
        raise SystemExit("need train_count or train_ratio")
    tasks = discover_tasks(dataset_dir)
    rng = random.Random(seed)
    n = len(tasks)
    n_train = train_count if train_count is not None else int(round(n * train_ratio))
    n_train = max(0, min(n_train, n))
    train_pool = rng.sample(tasks, n_train)
    batches = [train_pool[i:i + batch_size] for i in range(0, len(train_pool), batch_size)]
    return {
        "dataset": str(dataset_dir), "seed": seed, "n_tasks": n,
        "n_train": n_train, "batch_size": batch_size,
        "batches": [{"name": f"batch_{i:02d}", "tasks": [str(p) for p in b]}
                    for i, b in enumerate(batches, 1)],
        "final": {"tasks": [str(p) for p in tasks]},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, required=True, help="Harbor dataset dir (folder of task dirs).")
    ap.add_argument("--out", type=Path, required=True, help="Output splits dir.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--train-count", type=int, help="Number of tasks used for training batches.")
    group.add_argument("--train-ratio", type=float, help="Fraction of the dataset used for training.")
    ap.add_argument("--batch-size", type=int, required=True, help="Tasks per training batch.")
    ap.add_argument("--seed", type=int, default=42, help="Shuffle seed for the train pool sample.")
    args = ap.parse_args()

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    manifest = build_manifest(
        args.dataset.resolve(), train_count=args.train_count, train_ratio=args.train_ratio,
        batch_size=args.batch_size, seed=args.seed,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"[split] dataset={manifest['n_tasks']} tasks · train={manifest['n_train']} in "
        f"{len(manifest['batches'])} batch(es) of <={args.batch_size} · final=full {manifest['n_tasks']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
