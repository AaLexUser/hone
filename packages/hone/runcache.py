"""Recorded real runs, replayed when the same input comes back.

In demo mode (HONE_DEMO=1) every real MAJICS run that finishes (a commit or
no changes) is stored as a candidate entry under the fingerprint of its input.
After two reviewers pass it (docs/run-review.md), it is approved, and from
then on Start optimization on the same input replays it through Hone's own run
loop instead of starting Harbor. Only the stage executor is replaced. The
verifier, the commit and the experience log run as for any run. Outside demo
mode nothing is recorded or replayed.

The fingerprint is the SHA-256 of one canonical JSON document, see
`run_input`. Values that differ between two copies of the same input (ids,
commit hashes, timestamps, dates, the project folder) become numbered
placeholders, and the distinct values in order of first appearance are kept
with the entry. Each date format is its own kind, and a date's placeholder
holds its day offset from the first dated value, so only a batch whose dates
all move by the same number of days matches. A hit maps each recorded value to
the current one, as a whole token, in everything it replays.

Entries live in `<data dir>/run-cache/`, which a demo reset keeps, and in
`SHIPPED_DIR` in the source tree, read only. A local entry wins over a
shipped one with the same id.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from . import logedits

if TYPE_CHECKING:
    from .config import HoneConfig
    from .majics.pipeline import StageExecutor
    from .service import Hone
    from .store import DataDirs

log = logging.getLogger("hone.runcache")

RUN_CACHE_DIR = "run-cache"
SHIPPED_DIR = Path(__file__).parent / "demo" / "run-cache"
ENTRY_VERSION = 2
# A replay plays in about this long, however long the recorded run took.
REPLAY_TARGET_MS = 90_000
# Events Hone writes itself. A replay's run loop writes them again.
HONE_KINDS = frozenset({"log", "status"})
# The code that decides what a stage is asked, what it returns and what the
# host accepts from it, relative to SOURCE_ROOT. A change to it is a new input.
SOURCE_ROOT = Path(__file__).parent
SOURCE = ("majics", "patch.py")
_ENTRY_ID = re.compile(r"[\w-]+", re.ASCII)

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
    verdicts: list[str | None]       # per attempt, the rejection reason, None for the accepted one
    review: Review


# --------------------------------------------------------------------------- #
# The fingerprint
# --------------------------------------------------------------------------- #

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_NUMBER = {name: i for i, name in enumerate(_MONTHS.split("|"), 1)}
# A token never continues a word or a number. `\n` and `\t` escapes in JSON text are not part of a word.
_START = r"(?:(?<![0-9A-Za-z])|(?<=\\[nrt]))"
_END = r"(?![0-9A-Za-z])"
# Millisecond timestamps only as the value of these keys, in JSON or in JSON inside a JSON string.
_MS_AFTER = "|".join(f"(?<={re.escape(q + key + q + sep)})"
                     for key in ("timestamp", "at") for q in ('"', '\\"') for sep in (":", ": "))

# A date kind reads its text as (day, what follows the day), given the anchor
# day for a date written without a year.
DayReader = Callable[[str, "dt.date | None"], "tuple[dt.date, str] | None"]


def _iso_day(text: str, near: dt.date | None) -> tuple[dt.date, str]:
    return dt.date.fromisoformat(text[:10]), text[10:]


def _python_day(text: str, near: dt.date | None) -> tuple[dt.date, str]:
    year, month, day = (int(n) for n in re.findall(r"\d+", text))
    return dt.date(year, month, day), ""


def _written_day(text: str, near: dt.date | None) -> tuple[dt.date, str] | None:
    month = _MONTH_NUMBER[re.search(_MONTHS, text).group(0)]  # type: ignore[union-attr]
    day, *year = (int(n) for n in re.findall(r"\d+", text))
    if year:
        return dt.date(year[0], month, day), ""
    if near is None:
        return None
    candidates = []
    for y in (near.year - 1, near.year, near.year + 1):
        try:
            candidates.append(dt.date(y, month, day))
        except ValueError:
            pass
    return min(candidates, key=lambda c: abs((c - near).days)), ""


def _epoch_ms_day(text: str, near: dt.date | None) -> tuple[dt.date, str]:
    t = dt.datetime.fromtimestamp(int(text) / 1000, dt.UTC)
    return t.date(), f"T{t:%H:%M:%S}.{t.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class Kind:
    name: str
    pattern: str
    day: DayReader | None = None     # set for the kinds that write a date


# At one position the first kind that matches wins.
KINDS = (
    Kind("uuid", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    Kind("trace", r"ses_[0-9a-f]{8}"),
    Kind("isotime", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", _iso_day),
    Kind("isodate", r"\d{4}-\d{2}-\d{2}", _iso_day),
    Kind("pydate", r"date\(\d{4}, \d{1,2}, \d{1,2}\)", _python_day),       # a Python date literal
    Kind("epochms", rf"(?:{_MS_AFTER})\d{{13}}", _epoch_ms_day),
    Kind("dmy", rf"\d{{1,2}} (?:{_MONTHS}) \d{{4}}", _written_day),           # 17 November 2026
    Kind("mdy", rf"(?:{_MONTHS}) \d{{1,2}}, \d{{4}}", _written_day),          # November 17, 2026
    Kind("dm", rf"\d{{1,2}} (?:{_MONTHS})", _written_day),                    # 17 November
    Kind("md", rf"(?:{_MONTHS}) \d{{1,2}}", _written_day),                    # November 17
)
_DAY_READERS = {k.name: k.day for k in KINDS if k.day is not None}


def _token_alternative(name: str, pattern: str) -> str:
    return f"(?P<{name}>{_START}(?:{pattern}){_END})"


@dataclass(frozen=True)
class RunInput:
    fingerprint: str
    tokens: tuple[str, ...]


def canonicalize(text: str, literals: list[tuple[str, str]]) -> RunInput:
    """Replace each variable value with `⟨kind#n⟩`, n counting distinct values.
    `literals` are (kind, value) pairs to treat as variable values too. A date
    becomes `⟨kind#n+d⟩`, with d its day offset from the first date with a
    year, and anything written after the day (a time of day) kept."""
    ordered = sorted(literals, key=lambda kv: len(kv[1]), reverse=True)
    parts = [_token_alternative(f"{kind}{i}", re.escape(value)) for i, (kind, value) in enumerate(ordered)]
    parts += [_token_alternative(k.name, k.pattern) for k in KINDS]
    pattern = re.compile("|".join(parts))

    def read_day(kind: str, value: str, near: dt.date | None) -> tuple[dt.date, str] | None:
        try:
            return _DAY_READERS[kind](value, near)
        except ValueError:  # not a real day, such as 31 February
            return None

    anchor = next((read[0] for m in pattern.finditer(text) if m.lastgroup in _DAY_READERS
                   for read in [read_day(m.lastgroup, m.group(0), None)] if read is not None), None)
    seen: dict[str, int] = {}

    def placeholder(m: re.Match[str]) -> str:
        kind, value = re.sub(r"\d+$", "", m.lastgroup or ""), m.group(0)
        if kind not in _DAY_READERS:
            return f"⟨{kind}#{seen.setdefault(value, len(seen))}⟩"
        read = read_day(kind, value, anchor)
        if read is None or anchor is None:
            return value
        day, rest = read
        return f"⟨{kind}#{seen.setdefault(value, len(seen))}{(day - anchor).days:+d}{rest}⟩"

    canonical = pattern.sub(placeholder, text)
    return RunInput(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), tuple(seen))


def source_digest(root: Path) -> str:
    """SHA-256 over the files of SOURCE under `root`, with their paths."""
    digest = hashlib.sha256()
    for name in SOURCE:
        top = root / name
        files = (sorted(p for p in top.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
                 if top.is_dir() else [top])
        for path in files:
            body = path.read_bytes()
            digest.update(f"{path.relative_to(root).as_posix()}\0{len(body)}\0".encode())
            digest.update(body)
    return digest.hexdigest()


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
    their feedback in batch order, the base AGENTS.md and its version, the
    experience log the sandbox reads, the MAJICS configuration (providers,
    models, seats, reasoning, retry and timeout limits), and the source of the
    MAJICS package and the verifier, prompts and driver included."""
    traces = []
    cwds: list[str] = []
    for tid in run["trace_ids"]:
        path = hone.dirs.trace_path(tid)
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        row = hone.db.one("SELECT feedback FROM traces WHERE session_id = ?", (tid,)) or {}
        traces.append({"id": tid, "session": body, "feedback": row.get("feedback")})
        cwds += _session_cwds(body)
    history = logedits.sandbox_copy(hone.log_edits_payload())
    # Commit hashes change with the day the history was built.
    commits = {run["base_version_id"]} | {e.get(k) for e in history["entries"] for k in ("commit", "baseVersion")}
    document = {
        "version": ENTRY_VERSION,
        "source": source_digest(SOURCE_ROOT),
        "agentsMd": hone.git.file_at(run["base_version_id"]),
        "baseVersion": run["base_version_id"],
        "traces": traces,
        "history": history,
        "majics": hone.s.majics.model_dump(mode="json"),
        "optimization": hone.s.optimization.model_dump(mode="json"),
    }
    text = json.dumps(document, ensure_ascii=False, sort_keys=True)
    literals = [("cwd", c) for c in set(cwds)] + [("commit", c) for c in commits if isinstance(c, str) and c]
    return canonicalize(text, literals)


def _parse_entry(raw: Any) -> Entry | None:
    """`raw` as an entry of this version, or None when any part has the wrong shape."""
    def strings(v: Any) -> bool:
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    def segment(s: Any) -> bool:
        return (isinstance(s, dict) and isinstance(s.get("stage"), str) and isinstance(s.get("attempt"), int)
                and isinstance(s.get("endMs"), int) and isinstance(s.get("events"), list)
                and all(isinstance(e, list) and len(e) == 2 and isinstance(e[0], (int, float))
                        and isinstance(e[1], dict) for e in s["events"])
                and isinstance(s.get("artifacts"), dict)
                and all(isinstance(v, str) for v in s["artifacts"].values()))

    if not isinstance(raw, dict) or raw.get("version") != ENTRY_VERSION:
        return None
    review = raw.get("review")
    ok = (isinstance(raw.get("id"), str) and _ENTRY_ID.fullmatch(raw["id"]) is not None
          and all(isinstance(raw.get(k), str) for k in ("fingerprint", "sourceRunId", "recordedAt", "outcome", "title"))
          and strings(raw.get("tokens")) and isinstance(raw.get("durationMs"), int)
          and isinstance(raw.get("stages"), list) and all(segment(s) for s in raw["stages"])
          and isinstance(raw.get("verdicts"), list)
          and all(v is None or isinstance(v, str) for v in raw["verdicts"])
          and isinstance(review, dict) and review.get("status") in ("candidate", "approved", "rejected")
          and strings(review.get("notes")) and (review.get("at") is None or isinstance(review.get("at"), str)))
    return raw if ok else None  # type: ignore[return-value]


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
                entry = _parse_entry(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                log.warning("skipping run-cache file %s: %s", path, exc)
                continue
            if entry is None or entry["id"] != path.stem:
                log.warning("skipping run-cache file %s: not a version %d entry named by its id", path, ENTRY_VERSION)
                continue
            out[entry["id"]] = entry
        return out

    def entries(self) -> list[Entry]:
        merged = {**self._read_dir(self.shipped), **self._read_dir(self.local)}
        return sorted(merged.values(), key=lambda e: e["recordedAt"], reverse=True)

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries() if e["id"] == entry_id), None)

    def is_local(self, entry_id: str) -> bool:
        return (self.local / f"{entry_id}.json").exists()

    def store(self, entry: Entry) -> None:
        if not _ENTRY_ID.fullmatch(entry["id"]):
            raise ValueError(f"run-cache entry id {entry['id']!r} is not a file name")
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
        """The newest approved entry for this input that, replayed under the
        current verifier, reaches the verdicts it reached when it was recorded."""
        approved = [e for e in self.entries()
                    if e["fingerprint"] == inp.fingerprint and e["review"]["status"] == "approved"
                    and len(e["tokens"]) == len(inp.tokens)]
        base_file = hone.git.file_at(run["base_version_id"]).splitlines()
        for entry in sorted(approved, key=lambda e: e["review"]["at"] or "", reverse=True):
            replay = Replay(hone, entry, inp, run["id"])
            if replay.matches(base_file, run["trace_ids"], hone.s.optimization.max_attempts):
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
        self.verdicts: list[str | None] = []   # the service's attempt loop appends one per attempt

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
            "verdicts": self.verdicts,
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
        alternatives = "|".join(re.escape(k) for k in sorted(self.mapping, key=len, reverse=True))
        self._pattern = re.compile(f"{_START}(?:{alternatives}){_END}") if self.mapping else None
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

    def matches(self, base_file: list[str], trace_ids: list[str], max_attempts: int) -> bool:
        """Each recorded attempt, mapped, gets the verdict it got when it was
        recorded, so the replay commits what the reviewers saw committed and
        never asks for a stage that was not recorded."""
        from .majics.pipeline import attempt_verdicts

        artifacts = {(s["stage"], s["attempt"]): {name: self.text(t) for name, t in s["artifacts"].items()}
                     for s in self.entry["stages"]}
        replayed = attempt_verdicts(artifacts, self.run_id, base_file, trace_ids, max_attempts)
        return bool(self.entry["verdicts"]) and replayed == self.value(self.entry["verdicts"])

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

