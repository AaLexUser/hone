#!/usr/bin/env python3
"""Statistical check of epoch-over-epoch improvement on the same tasks.

Reads all stage reports of an experiment (``epoch_*/batch_*/report.json``),
pairs every task's outcome in the FIRST epoch against the LAST epoch, and runs
an exact McNemar test on the discordant pairs (tasks whose outcome changed).

McNemar exact: with b = wrong->right flips and c = right->wrong flips,
p = P(X >= b | X ~ Binomial(b + c, 0.5)) — one-sided, testing improvement.

Usage:
    python scripts/bench/stats.py <exp_dir> [first_epoch] [last_epoch]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def binom_sf(k: int, n: int, p: float = 0.5) -> float:
    """One-sided exact binomial tail: P(X >= k)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def epoch_outcomes(exp: Path, epoch: int) -> dict[str, bool]:
    """Task -> ok for every batch of the given epoch."""
    out: dict[str, bool] = {}
    for report in sorted(exp.glob(f"epoch_{epoch:02d}/batch_*/report.json")):
        r = json.loads(report.read_text())
        out.update({t["task"]: bool(t["ok"]) for t in r.get("trials", [])})
    return out


def main() -> None:
    exp = Path(sys.argv[1] if len(sys.argv) > 1 else "experiments/officeqa-run1")
    epochs = sorted({int(p.name.split("_")[1]) for p in exp.glob("epoch_*")})
    if len(epochs) < 2:
        raise SystemExit(f"need at least 2 epochs with reports under {exp}")
    first, last = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (epochs[0], epochs[-1])

    a, b_out = epoch_outcomes(exp, first), epoch_outcomes(exp, last)
    common = sorted(set(a) & set(b_out))
    if not common:
        raise SystemExit(f"no common tasks between epoch {first} and epoch {last}")

    up = [t for t in common if b_out[t] and not a[t]]      # wrong -> right
    down = [t for t in common if a[t] and not b_out[t]]    # right -> wrong
    b, c = len(up), len(down)
    n_disc = b + c
    p_value = binom_sf(b, n_disc) if n_disc else 1.0

    print(f"epoch {first}: {sum(a[t] for t in common)}/{len(common)} correct")
    print(f"epoch {last}:  {sum(b_out[t] for t in common)}/{len(common)} correct")
    print(f"flipped up (wrong->right): {b} {up}")
    print(f"flipped down (right->wrong): {c} {down}")
    print(f"McNemar exact (one-sided): b={b}, c={c}, n={n_disc}, p={p_value:.4f}")
    verdict = "SIGNIFICANT (p <= 0.05)" if p_value <= 0.05 and b > c else "NOT significant"
    print(f"verdict: {verdict}")
    sys.exit(0 if (p_value <= 0.05 and b > c) else 1)


if __name__ == "__main__":
    main()
