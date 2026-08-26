"""log_edits.json — the experience history the optimizer learns from.

A durable, service-owned JSON file at /data/log_edits.json: one entry per
completed optimizer iteration, recording the commit, the applied line changes
with their rationale and trace evidence, the hypothesis (signal), and the
outcome — including runs that changed nothing or were rejected. The optimizer
reads it at the start of every run so past experiments inform new ones; the
service appends only after the verifier accepted a result, so the log
describes actually-applied history. Entries are cumulative across branches
and stored newest first: the Git history of AGENTS.md stays the per-version
source of truth, while this file is the running memory of what was tried and
why.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import patch

LOG_VERSION = 1

# The sandbox copy handed to MAJICS is capped: enough experience to
# matter, small enough to leave room for the traces in the model context.
SANDBOX_MAX_ENTRIES = 50


def empty_log() -> dict[str, Any]:
    return {"version": LOG_VERSION, "entries": []}


def ensure(path: Path) -> None:
    """Create the empty log on first boot; idempotent afterwards."""
    if not path.exists():
        write_log(path, empty_log())


def _entry_num(entry: Any) -> int:
    """Numeric part of an entry id (e_007 -> 7); 0 when absent or malformed."""
    try:
        return int(str(entry.get("id", "")).split("_")[-1])
    except (ValueError, AttributeError):
        return 0


def read_log(path: Path) -> dict[str, Any]:
    """Parse the durable log; a corrupt file is moved aside, never destroyed.

    Newest first is the file's invariant, so files written oldest-first (by
    older Hone versions) are healed to the new order on read.
    """
    if not path.exists():
        return empty_log()
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        path.rename(backup)
        return empty_log()
    if not isinstance(log, dict) or not isinstance(log.get("entries"), list):
        return empty_log()
    log.setdefault("version", LOG_VERSION)
    log["entries"].sort(key=_entry_num, reverse=True)
    return log


def write_log(path: Path, log: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def next_entry_number(log: dict[str, Any]) -> int:
    return max((_entry_num(e) for e in log["entries"]), default=0) + 1


def append_entry(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Store one entry; keyed on runId so re-recording a run replaces, not duplicates."""
    log = read_log(path)
    at = next(
        (i for i, e in enumerate(log["entries"]) if e.get("runId") == entry.get("runId")), None
    )
    eid = log["entries"][at]["id"] if at is not None else f"e_{next_entry_number(log):03d}"
    entry = {"id": eid, "at": int(time.time() * 1000), **entry}
    if at is None:
        log["entries"].insert(0, entry)  # newest first
    else:
        log["entries"][at] = entry
    write_log(path, log)
    return entry


def applied_entry(
    run: dict[str, Any],
    sha: str,
    branch: str,
    title: str,
    body: str,
    result: dict[str, Any],
    changes: list[patch.Change],
    base_file: list[str],
    new_file: list[str],
) -> dict[str, Any]:
    """The experience record of a verified, committed optimizer iteration."""
    adds, dels = patch.diff_stats(base_file, new_file)
    entry = {
        "outcome": "applied",
        "runId": run["id"],
        "commit": sha,
        "branch": branch,
        "baseVersion": run["base_version_id"],
        "model": run["model"],
        "attempts": run.get("attempts", 1),
        "title": title,
        "body": body,
        "signal": result.get("signal", ""),
        "traces": list(run["trace_ids"]),
        "changes": [c.as_dict() for c in changes],
        "stats": {"adds": adds, "dels": dels},
    }
    if result.get("review"):
        entry["review"] = result["review"]
    return entry


def outcome_entry(
    run: dict[str, Any],
    outcome: str,
    note: str,
    title: str = "",
    body: str = "",
    signal: str = "",
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A run that changed nothing (`no-changes`) or was rejected (`failed`)."""
    entry = {
        "outcome": outcome,
        "runId": run["id"],
        "commit": None,
        "baseVersion": run["base_version_id"],
        "model": run["model"],
        "attempts": run.get("attempts", 1),
        "title": title,
        "body": body,
        "signal": signal,
        "traces": list(run["trace_ids"]),
        "changes": [],
        "note": note,
    }
    if review:
        entry["review"] = review
    return entry


def sandbox_copy(log: dict[str, Any], limit: int = SANDBOX_MAX_ENTRIES) -> dict[str, Any]:
    """The copy MAJICS sees: newest entries first, with truncation flagged."""
    entries = log["entries"]
    if limit and len(entries) > limit:
        return {
            "version": log.get("version", LOG_VERSION),
            "truncated": True,
            "total": len(entries),
            "note": f"Showing the {limit} most recent of {len(entries)} entries, newest first.",
            "entries": entries[:limit],
        }
    return log
