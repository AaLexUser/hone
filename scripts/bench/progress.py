#!/usr/bin/env python3
"""Progress monitoring for Harbor experiment runs (epoch-aware).

Two roles, both benchmark-agnostic (any Harbor experiment laid out as
``<exp>/epoch_XX/batch_YY/report.json``; legacy ``<exp>/batch_YY/report.json``
counts as epoch 1):

1. Human/agent analytics — text summaries of how each batch improved or
   regressed versus the previous run of the same batch (previous epoch).
   The experiment runner embeds these notes into per-task feedback so the
   optimizing agent receives the progress information in text form.
2. CLI monitoring — print the per-epoch score table with deltas, and live
   trial counts for a stage that is still running.

Usage:
    python progress.py <exp_dir>              # score table + epoch deltas
    python progress.py <exp_dir> --live       # also count finished trials of the latest stage
    python progress.py <jobs_dir> [baseline]  # legacy: live trials of one harbor job dir
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _stage_key(report_path: Path) -> tuple[int, int]:
    """(epoch, batch_index) sort key for a stage report path."""
    parts = report_path.relative_to(report_path.parents[2]).parts
    epoch = int(parts[0].split("_")[1]) if parts[0].startswith("epoch_") else 1
    batch = int(parts[1].split("_")[1]) if len(parts) > 2 and parts[1].startswith("batch_") else 0
    return epoch, batch


def load_stage_reports(exp: Path) -> dict[str, list[dict]]:
    """All stage reports grouped by batch name, sorted by epoch."""
    reports: dict[str, list[dict]] = {}
    for pattern in ("epoch_*/batch_*/report.json", "batch_*/report.json"):
        for p in sorted(exp.glob(pattern), key=_stage_key):
            try:
                r = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            r.setdefault("epoch", _stage_key(p)[0])
            r.setdefault("batch", p.parent.name)
            reports.setdefault(p.parent.name, []).append(r)
    return reports


def _task_outcomes(report: dict) -> dict[str, bool]:
    return {t["task"]: bool(t["ok"]) for t in report.get("trials", [])}


def _task_answer(report: dict, task: str) -> str:
    for t in report.get("trials", []):
        if t["task"] == task:
            got = (t.get("predicted") or "").strip()
            if "</FINAL_ANSWER>" in got or "<FINAL_ANSWER>" in got:
                got = got.split(">", 1)[-1].split("<", 1)[0].strip()
            return got or "(no answer)"
    return "(no answer)"


def pre_run_notes(prev: dict) -> tuple[str, dict[str, str]]:
    """Batch line + per-task notes derived ONLY from the previous run of the same
    batch, so they can be attached to feedback before the new run executes.

    The text tells the optimizing agent what failed before, with what answer,
    and what already worked and must not break.
    """
    outcomes = _task_outcomes(prev)
    failed = [t for t, ok in outcomes.items() if not ok]
    solved = [t for t, ok in outcomes.items() if ok]
    batch_note = (f"Previous run of this batch (epoch {prev.get('epoch', '?')}): "
                  f"{len(solved)}/{len(outcomes)} correct. "
                  f"Previously failed tasks: {', '.join(failed) or 'none'}. "
                  f"Previously solved: {', '.join(solved) or 'none'}.")
    notes: dict[str, str] = {}
    for t in failed:
        gt = next((x.get("ground_truth") for x in prev.get("trials", []) if x["task"] == t), "?")
        notes[t] = (f"Progress note: this task FAILED the previous run of this batch "
                    f"(previous answer: {_task_answer(prev, t)}; expected: {gt or '?'}). "
                    "The rules in place did not solve it — a different approach is needed.")
    for t in solved:
        notes[t] = "Progress note: solved correctly in the previous run of this batch — keep what works."
    return batch_note, notes


def batch_progress(prev: dict | None, cur: dict) -> tuple[str, dict[str, str]]:
    """Batch-level progress line + per-task notes vs the previous run of the same batch.

    The text is written for an agent to consume: it names regressions,
    newly solved tasks, and persistent failures with their previous answers.
    """
    if prev is None:
        line = (f"Progress: first recorded run of {cur.get('batch', 'this batch')} — "
                f"{cur.get('hits', 0)}/{cur.get('total', 0)} correct. "
                "No previous run to compare yet.")
        return line, {}
    prev_ok, cur_ok = _task_outcomes(prev), _task_outcomes(cur)
    common = [t for t in cur_ok if t in prev_ok]
    solved = [t for t in common if cur_ok[t] and not prev_ok[t]]
    regressed = [t for t in common if prev_ok[t] and not cur_ok[t]]
    still_wrong = [t for t in common if not cur_ok[t] and not prev_ok[t]]
    both_right = [t for t in common if cur_ok[t] and prev_ok[t]]
    line = (f"Progress vs previous run of this batch: {cur.get('hits', 0)}/{cur.get('total', 0)} "
            f"correct now, was {prev.get('hits', 0)}/{prev.get('total', 0)}. "
            f"Newly solved: {', '.join(solved) or 'none'}. "
            f"Regressions (was correct, failed now): {', '.join(regressed) or 'none'}. "
            f"Still failing: {', '.join(still_wrong) or 'none'}.")
    notes: dict[str, str] = {}
    for t in common:
        if cur_ok[t] and prev_ok[t]:
            notes[t] = "Progress note: solved correctly in the previous run of this batch too."
        elif cur_ok[t] and not prev_ok[t]:
            notes[t] = ("Progress note: failed in the previous run of this batch, solved correctly now — "
                        "keep whatever changed.")
        elif prev_ok[t] and not cur_ok[t]:
            notes[t] = ("Progress note: REGRESSION — solved correctly in the previous run but failed now "
                        f"(previous answer: {_task_answer(prev, t)}).")
        else:
            notes[t] = ("Progress note: failed in every run of this batch so far — the current rules did NOT "
                        f"fix it. Previous answer: {_task_answer(prev, t)}; now: {_task_answer(cur, t)}. "
                        "The recurring rules are not working for this task; a different approach is needed.")
    for t in both_right:
        notes.pop(t, None)  # keep only actionable notes
    return line, notes


def experiment_summary(exp: Path) -> list[str]:
    lines: list[str] = []
    for batch, runs in load_stage_reports(exp).items():
        prev = None
        for r in runs:
            line, _ = batch_progress(prev, r)
            lines.append(f"epoch {r['epoch']} {batch}: {r.get('hits', 0)}/{r.get('total', 0)} — {line}")
            prev = r
    return lines


def live_trials(jobs_dir: Path) -> int:
    return sum(1 for _ in jobs_dir.glob("*/result.json"))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    live = "--live" in sys.argv
    target = Path(args[0]) if args else REPO / "experiments/officeqa-run1"
    if (target / "config.json").exists() or any(target.glob("epoch_*")) or any(target.glob("batch_*")):
        for line in experiment_summary(target):
            print(line)
        if live:
            stages = sorted(target.glob("epoch_*/batch_*/jobs/*/"),
                            key=lambda p: p.stat().st_mtime)
            if stages:
                newest = max(stages, key=lambda p: p.stat().st_mtime)
                print(f"live: {newest.parent.parent.relative_to(target)}: "
                      f"{live_trials(newest.parent)} finished trial(s)")
    else:
        # legacy mode: a harbor jobs dir (+ optional baseline) — live trial counts
        hits = errs = total = 0
        for p in sorted(target.glob("*/result.json")):
            try:
                r = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            total += 1
            hits += rew is not None and float(rew) >= 1.0
            errs += bool(r.get("exception_info"))
        print(f"trials={total} hits={hits} score={hits / max(1, total):.1%} errors={errs}")


if __name__ == "__main__":
    main()
