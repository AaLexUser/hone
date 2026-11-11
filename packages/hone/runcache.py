"""Recorded real runs, replayed when the same input comes back.

Every real MAJICS run that finishes (a commit or no changes) is stored as a
candidate entry under the fingerprint of its input. After two reviewers pass
it (docs/run-review.md), it is approved, and from then on Start optimization
on the same input replays it through Hone's own run loop instead of starting
Harbor. Only the stage executor is replaced. The verifier, the commit and the
experience log run as for any run.

The fingerprint is the SHA-256 of one canonical JSON document, see
`run_input`. Values that differ between two copies of the same input (ids,
timestamps, dates, the project folder) become numbered placeholders, and the
distinct values in order of first appearance are kept with the entry. A hit
on another day maps each recorded value to the current one in everything it
replays.

Entries live in `<data dir>/run-cache/`, which a demo reset keeps, and in
`SHIPPED_DIR` in the source tree, read only. A local entry wins over a
shipped one with the same id.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from . import logedits, patch

if TYPE_CHECKING:
    from .config import HoneConfig
    from .majics.pipeline import StageExecutor
    from .service import Hone
    from .store import DataDirs

RUN_CACHE_DIR = "run-cache"
SHIPPED_DIR = Path(__file__).parent / "demo" / "run-cache"
ENTRY_VERSION = 1
# A replay plays in about this long, however long the recorded run took.
REPLAY_TARGET_MS = 90_000
# Events Hone writes itself. A replay's run loop writes them again.
HONE_KINDS = frozenset({"log", "status"})

Status = Literal["candidate", "approved", "rejected"]


class Segment(TypedDict):
    stage: str
    attempt: int
    endMs: int                       # when the stage returned, from its launch
    events: list[list[Any]]          # [offset ms from launch, event as the driver posted it]
    artifacts: dict[str, str]        # what the sandbox handed back


class Review(TypedDict):
    status: Status
    notes: list[str]
    at: str | None                   # when the status was last set


class Entry(TypedDict):
    version: int
    id: str
    fingerprint: str
    tokens: list[str]                # the distinct variable values of the recorded input
    sourceRunId: str
    recordedAt: str
    durationMs: int
    outcome: str                     # succeeded or no-changes
    title: str
    stages: list[Segment]
    review: Review


# --------------------------------------------------------------------------- #
# The fingerprint
# --------------------------------------------------------------------------- #

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# Order matters, the first alternative that matches at a position wins.
_VARIABLE = [
    ("uuid", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    ("trace", r"ses_[0-9a-f]{8}"),
    ("time", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    ("date", r"\d{4}-\d{2}-\d{2}"),
    ("date", r"date\(\d{4}, \d{1,2}, \d{1,2}\)"),     # a Python date literal in a script
    ("ms", r"(?<!\d)1\d{12}(?!\d)"),
    ("date", rf"\d{{1,2}} (?:{_MONTHS})(?: \d{{4}})?"),
    ("date", rf"(?:{_MONTHS}) \d{{1,2}}(?:, \d{{4}})?"),
]
# Log entries name the commits of their day, and git hashes change with the date.
_HISTORY_DROP = ("at", "commit", "baseVersion")


@dataclass(frozen=True)
class RunInput:
    fingerprint: str
    tokens: tuple[str, ...]


def canonicalize(text: str, literals: list[str]) -> RunInput:
    """Replace each variable value with `⟨kind#n⟩`, n counting distinct values."""
    parts = [f"(?P<cwd{i}>{re.escape(lit)})" for i, lit in enumerate(literals)]
    parts += [f"(?P<{kind}{i}>{rx})" for i, (kind, rx) in enumerate(_VARIABLE)]
    pattern = re.compile("|".join(parts))
    seen: dict[str, int] = {}

    def placeholder(m: re.Match[str]) -> str:
        kind = re.sub(r"\d+$", "", m.lastgroup or "")
        n = seen.setdefault(m.group(0), len(seen))
        return f"⟨{kind}#{n}⟩"

    canonical = pattern.sub(placeholder, text)
    return RunInput(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), tuple(seen))


def _session_cwds(body: str) -> list[str]:
    for line in body.splitlines():
        if line.strip():
            try:
                header = json.loads(line)
            except json.JSONDecodeError:
                return []
            cwd = header.get("cwd") if isinstance(header, dict) and header.get("type") == "session" else None
            return [cwd] if isinstance(cwd, str) and cwd else []
    return []


def run_input(hone: Hone, run: dict[str, Any]) -> RunInput:
    """What decides a run's result, in canonical form: the batch traces with
    their feedback in batch order, the base AGENTS.md, the experience log the
    sandbox reads, and the MAJICS configuration (providers, models, seats,
    reasoning, retry and timeout limits, and the prompts)."""
    from .majics.assets import PROMPT_FILES

    traces = []
    cwds: list[str] = []
    for tid in run["trace_ids"]:
        path = hone.dirs.trace_path(tid)
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        row = hone.db.one("SELECT feedback FROM traces WHERE session_id = ?", (tid,)) or {}
        traces.append({"id": tid, "session": body, "feedback": row.get("feedback")})
        cwds += _session_cwds(body)
    history = logedits.sandbox_copy(hone.log_edits_payload())
    history = {**history, "entries": [{k: v for k, v in e.items() if k not in _HISTORY_DROP}
                                      for e in history["entries"]]}
    document = {
        "version": ENTRY_VERSION,
        "agentsMd": hone.git.file_at(run["base_version_id"]),
        "traces": traces,
        "history": history,
        "majics": hone.s.majics.model_dump(mode="json"),
        "optimization": hone.s.optimization.model_dump(mode="json"),
        "prompts": PROMPT_FILES,
    }
    text = json.dumps(document, ensure_ascii=False, sort_keys=True)
    # Longest first, so a folder inside another folder is not matched first.
    return canonicalize(text, sorted(set(cwds), key=len, reverse=True))


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunCache:
    def __init__(self, local: Path, shipped: Path = SHIPPED_DIR) -> None:
        self.local = local
        self.shipped = shipped

    def _read_dir(self, d: Path) -> dict[str, Entry]:
        out: dict[str, Entry] = {}
        for path in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("version") == ENTRY_VERSION:
                out[entry["id"]] = entry  # type: ignore[assignment]
        return out

    def entries(self) -> list[Entry]:
        merged = {**self._read_dir(self.shipped), **self._read_dir(self.local)}
        return sorted(merged.values(), key=lambda e: e["recordedAt"], reverse=True)

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries() if e["id"] == entry_id), None)

    def is_local(self, entry_id: str) -> bool:
        return (self.local / f"{entry_id}.json").exists()

    def store(self, entry: Entry) -> None:
        self.local.mkdir(parents=True, exist_ok=True)
        tmp = self.local / f".{entry['id']}.json.tmp"
        tmp.write_text(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        tmp.rename(self.local / f"{entry['id']}.json")

    def set_review(self, entry_id: str, status: Status, notes: list[str]) -> Entry:
        """Record the reviewers' verdict. A shipped entry gets a local copy."""
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        notes = [n.strip() for n in notes if n.strip()]
        if status == "approved" and not notes:
            raise ValueError("approving an entry needs the reviewers' notes")
        entry["review"] = {"status": status, "notes": notes, "at": _now_iso()}
        self.store(entry)
        return entry

    def replay_for(self, hone: Hone, run: dict[str, Any], inp: RunInput) -> Replay | None:
        """The newest approved entry for this input whose proposal still applies."""
        approved = [e for e in self.entries()
                    if e["fingerprint"] == inp.fingerprint and e["review"]["status"] == "approved"
                    and len(e["tokens"]) == len(inp.tokens)]
        for entry in sorted(approved, key=lambda e: e["review"]["at"] or "", reverse=True):
            replay = Replay(hone, entry, inp, run["id"])
            if replay.applies(hone.git.file_at(run["base_version_id"]).splitlines(), run["trace_ids"]):
                return replay
        return None


# --------------------------------------------------------------------------- #
# Recording a real run
# --------------------------------------------------------------------------- #


class Recorder:
    """Wraps the Harbor executor of one real run and keeps, per stage, the
    events the driver posted and the artifacts it returned."""

    def __init__(self, hone: Hone, run_id: str, inp: RunInput) -> None:
        self.hone = hone
        self.run_id = run_id
        self.input = inp
        self.segments: list[Segment] = []

    def executor(self, settings: HoneConfig, dirs: DataDirs, run_id: str,
                 emit: Callable[..., Any]) -> StageExecutor:
        """An `ExecutorFactory` for `MajicsPipeline`."""
        from .majics import executor as harbor

        return _RecordingExecutor(self, harbor.HarborMajicsExecutor(settings, dirs, run_id, emit))

    def entry(self, run: dict[str, Any], outcome: str, title: str) -> Entry:
        recorded = _now_iso()
        return {
            "version": ENTRY_VERSION,
            "id": f"{re.sub(r'[-:]', '', recorded[:19])}-{run['id']}",
            "fingerprint": self.input.fingerprint,
            "tokens": list(self.input.tokens),
            "sourceRunId": run["id"],
            "recordedAt": recorded,
            "durationMs": int(run.get("duration_ms") or 0),
            "outcome": outcome,
            "title": title,
            "stages": self.segments,
            "review": {"status": "candidate", "notes": [], "at": None},
        }


class _RecordingExecutor:
    def __init__(self, recorder: Recorder, inner: StageExecutor) -> None:
        self.recorder = recorder
        self.inner = inner

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path:
        hone, run_id = self.recorder.hone, self.recorder.run_id
        from .majics.runtime import collect_artifacts

        launched = hone._rel_at(run_id)
        seen = len(hone.events_of(run_id))
        job_dir = await self.inner.run(stage, task_dir, attempt)
        events = [[ev["at"] - launched, {k: v for k, v in ev.items() if k != "at"}]
                  for ev in hone.events_of(run_id)[seen:] if ev.get("kind") not in HONE_KINDS]
        self.recorder.segments.append({
            "stage": stage,
            "attempt": attempt,
            "endMs": hone._rel_at(run_id) - launched,
            "events": events,
            "artifacts": collect_artifacts(job_dir),
        })
        return job_dir


# --------------------------------------------------------------------------- #
# Replaying an entry
# --------------------------------------------------------------------------- #


class Replay:
    """One approved entry bound to the current run: recorded values map to
    the current ones, and time runs `speed` times faster."""

    def __init__(self, hone: Hone, entry: Entry, inp: RunInput, run_id: str) -> None:
        self.hone = hone
        self.entry = entry
        self.run_id = run_id
        pairs = {**dict(zip(entry["tokens"], inp.tokens, strict=True)), entry["sourceRunId"]: run_id}
        self.mapping = {old: new for old, new in pairs.items() if old != new}
        self._pattern = (re.compile("|".join(re.escape(k) for k in sorted(self.mapping, key=len, reverse=True)))
                         if self.mapping else None)
        self.speed = max(1.0, entry["durationMs"] / REPLAY_TARGET_MS)

    def text(self, value: str) -> str:
        return self._pattern.sub(lambda m: self.mapping[m.group(0)], value) if self._pattern else value

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.value(v) for k, v in value.items()}
        return value

    def segment(self, stage: str, attempt: int) -> Segment:
        for seg in self.entry["stages"]:
            if seg["stage"] == stage and seg["attempt"] == attempt:
                return seg
        raise RuntimeError(f"recorded run {self.entry['sourceRunId']} has no {stage} attempt {attempt}")

    def applies(self, base_file: list[str], trace_ids: list[str]) -> bool:
        """The recorded final proposal, mapped, still verifies on this base."""
        proposals = [s for s in self.entry["stages"] if s["stage"] == "propose" and "proposal.json" in s["artifacts"]]
        if not proposals:
            return False
        try:
            proposal = json.loads(self.text(proposals[-1]["artifacts"]["proposal.json"]))
        except json.JSONDecodeError:
            return False
        edits = proposal.get("edits") if isinstance(proposal, dict) else None
        if not isinstance(edits, list):
            return False
        if not edits:
            return True
        try:
            patch.verify_commit_message({"commit": {"title": proposal.get("commit_title") or "",
                                                    "body": proposal.get("commit_body") or ""}})
            patch.apply_proposal_edits(edits, base_file, trace_ids)
        except patch.PatchError:
            return False
        return True

    def note(self) -> dict[str, Any]:
        """The machine readable record of where this run came from."""
        return {
            "entryId": self.entry["id"],
            "sourceRunId": self.entry["sourceRunId"],
            "recordedAt": self.entry["recordedAt"],
            "fingerprint": self.entry["fingerprint"],
            "review": self.entry["review"],
        }

    def executor(self, settings: HoneConfig, dirs: DataDirs, run_id: str,
                 emit: Callable[..., Any]) -> StageExecutor:
        """An `ExecutorFactory` for `MajicsPipeline`."""
        return _ReplayExecutor(self, dirs, emit)


class _ReplayExecutor:
    def __init__(self, replay: Replay, dirs: DataDirs, emit: Callable[..., Any]) -> None:
        self.replay = replay
        self.dirs = dirs
        self.emit = emit

    async def _sleep(self, ms: float) -> None:
        if ms > 0:
            await asyncio.sleep(ms / self.replay.speed / 1000)

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path:
        from .majics.runtime import emit_launch

        replay, run_id = self.replay, self.replay.run_id
        emit_launch(self.emit, stage)
        seg = replay.segment(stage, attempt)
        last = 0
        for offset, event in seg["events"]:
            await self._sleep(offset - last)
            last = max(last, offset)
            event = replay.value(event)
            if isinstance(event.get("durationMs"), (int, float)):
                event["durationMs"] = round(event["durationMs"] / replay.speed)
            await replay.hone.record_pipeline_event(run_id, event)
        await self._sleep(seg["endMs"] - last)
        job_dir = self.dirs.run_dir(run_id) / "majics" / f"{stage}-a{attempt}" / "jobs" / f"{run_id}-{stage}-a{attempt}"
        artifacts = job_dir / f"task__{secrets.token_hex(4)[:7]}" / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        for name, text in seg["artifacts"].items():
            (artifacts / name).write_text(replay.text(text), encoding="utf-8")
        return job_dir

