"""Checks for the run cache. Run with `uv run python -m hone.runcache_check`.

Each check builds Hone on its own scratch data dir. A stand-in replaces the
Harbor executor and returns scripted stage artifacts, so no sandbox starts.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import patch, runcache
from .majics import executor as harbor
from .majics import pipeline
from .service import Hone
from .settings import load_settings

SCRIPT: dict[tuple[str, int], dict[str, str]] = {}


class StandInHarbor:
    """Returns the artifacts SCRIPT holds for each (stage, attempt)."""

    def __init__(self, settings: Any, dirs: Any, run_id: str, emit: Callable[..., Any]) -> None:
        self.dirs = dirs
        self.run_id = run_id

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path:
        job_dir = self.dirs.run_dir(self.run_id) / "majics" / f"{stage}-a{attempt}" / "jobs" / "stand-in"
        out = job_dir / "task__stand-in" / "artifacts"
        out.mkdir(parents=True, exist_ok=True)
        for name, text in SCRIPT[stage, attempt].items():
            (out / name).write_text(text, encoding="utf-8")
        return job_dir


harbor.HarborMajicsExecutor = StandInHarbor  # type: ignore[assignment,misc]
pipeline.HarborMajicsExecutor = StandInHarbor  # type: ignore[assignment,misc]

ROOT = Path(tempfile.mkdtemp(prefix="hone-runcache-check-"))


def make_hone(name: str, *, demo: bool = True) -> Hone:
    s = load_settings()
    return Hone(s.model_copy(update={"service": s.service.model_copy(
        update={"data_dir": ROOT / name, "demo": demo})}))


def ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def session(day: dt.date, cwd: str, *, deadline_days: int = 7, us: bool = False) -> bytes:
    """A Pi session on `day` that writes a letter dated `day` with a reply deadline."""
    at = dt.datetime.combine(day, dt.time(9, 25), dt.UTC)
    dated = f"{day:%B} {day.day}, {day.year}" if us else f"{day.day} {day:%B} {day.year}"
    deadline = (day + dt.timedelta(days=deadline_days)).isoformat()
    lines = [
        {"type": "session", "id": str(uuid.uuid4()), "cwd": cwd, "timestamp": at.isoformat().replace("+00:00", "Z")},
        {"type": "message", "timestamp": at.isoformat().replace("+00:00", "Z"), "message": {
            "role": "user", "timestamp": ms(at),
            "content": [{"type": "text", "text": f"Write the offer letter. Date: {dated}. Respond by {deadline}."}]}},
    ]
    return "".join(json.dumps(line) + "\n" for line in lines).encode()


def add_batch(hone: Hone, day: dt.date, cwd: str, **kw: Any) -> list[str]:
    ids = []
    for i in range(2):
        trace = hone.upsert_trace(uuid.uuid4().hex, session(day + dt.timedelta(days=i), cwd, **kw), None)
        hone.set_feedback(trace["id"], "The deadline is wrong.")
        ids.append(trace["id"])
        time.sleep(0.005)  # batch order follows arrival in milliseconds
    return ids


def fingerprint(hone: Hone) -> runcache.RunInput:
    batch = [t["session_id"] for t in reversed(hone.db.traces()) if t["status"] == "new"]
    return runcache.run_input(hone, {"id": "r_0000", "trace_ids": batch, "base_version_id": hone.current_id})


def script(batch: list[str], *, first_title: str) -> None:
    """Attempt 1 proposes with `first_title`, attempt 2 with a valid title."""
    review = {"version": 1, "summary": "Deadlines drift.", "findings": [], "hypotheses": [],
              "directions": [], "unresolved": []}
    edit = {"oldText": "", "newText": "## Offer letters\n- Give the reply deadline seven days after the letter date.",
            "rationale": f"{batch[0]} got the deadline wrong.", "evidence": batch}

    def proposal(title: str) -> str:
        return json.dumps({"edits": [edit], "commit_title": title, "commit_body": f"Seen in {batch[0]}."})

    SCRIPT.clear()
    SCRIPT["review", 1] = {"review.json": json.dumps(review)}
    SCRIPT["propose", 1] = {"proposal.json": proposal(first_title)}
    SCRIPT["propose", 2] = {"proposal.json": proposal("docs: give offer letters a fixed reply deadline")}


async def finish(hone: Hone) -> dict[str, Any]:
    started = hone.start_run(batch_size=8)
    await hone._run_task  # type: ignore[misc]
    run = hone.run_payload(started["id"])
    assert run is not None
    return run


def cache_files(hone: Hone) -> list[str]:
    d = hone.s.service.data_dir / runcache.RUN_CACHE_DIR
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


# --------------------------------------------------------------------------- #


def check_date_formats_and_gaps() -> None:
    us = runcache.canonicalize("Date: November 17, 2026. Respond by 2026-11-21.", [])
    uk = runcache.canonicalize("Date: 17 November 2026. Respond by 2026-11-24.", [])
    assert us.fingerprint != uk.fingerprint, "US date with a 4 day deadline hashes apart from UK date with 7 days"
    same_gap_us = runcache.canonicalize("Date: November 17, 2026. Respond by 2026-11-24.", [])
    assert same_gap_us.fingerprint != uk.fingerprint, "a date format alone changes the fingerprint"
    wrong_gap = runcache.canonicalize("Date: 17 November 2026. Respond by 2026-11-21.", [])
    assert wrong_gap.fingerprint != uk.fingerprint, "a deadline gap alone changes the fingerprint"
    shifted = runcache.canonicalize("Date: 20 November 2026. Respond by 2026-11-27.", [])
    assert shifted.fingerprint == uk.fingerprint, "the same text three days later hashes the same"
    assert shifted.tokens == ("20 November 2026", "2026-11-27"), shifted.tokens
    numbers = runcache.canonicalize('{"tokens": 1794501002431, "timestamp": 1794501002432}', [])
    assert numbers.tokens == ("1794501002432",), f"only a timestamp key's value is a timestamp: {numbers.tokens}"


def check_shifted_batch_matches() -> None:
    a, b = make_hone("shift-a"), make_hone("shift-b")
    add_batch(a, dt.date(2026, 11, 13), "/work/booth-a")
    add_batch(b, dt.date(2026, 11, 20), "/work/booth-b")
    fa, fb = fingerprint(a), fingerprint(b)
    assert fa.fingerprint == fb.fingerprint, "a batch moved by whole days, with other ids and folder, matches"
    assert fa.tokens != fb.tokens
    for name, kw in (("gap", {"deadline_days": 4}), ("us", {"us": True})):
        c = make_hone(f"shift-{name}")
        add_batch(c, dt.date(2026, 11, 13), "/work/booth-a", **kw)
        assert fingerprint(c).fingerprint != fa.fingerprint, f"a batch with the {name} flaw does not match"
        c.close()
    a.close()
    b.close()


def check_source_change() -> None:
    hone = make_hone("source")
    add_batch(hone, dt.date(2026, 11, 13), "/work/booth")
    copy = ROOT / "source-copy"
    for name in runcache.SOURCE:
        src = runcache.SOURCE_ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, copy / name)
    real = runcache.SOURCE_ROOT
    try:
        before = fingerprint(hone).fingerprint
        runcache.SOURCE_ROOT = copy
        assert fingerprint(hone).fingerprint == before, "an unchanged copy of the source hashes the same"
        driver = copy / "majics" / "driver" / "majics.ts"
        driver.write_text(driver.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
        assert fingerprint(hone).fingerprint != before, "a changed driver changes the fingerprint"
    finally:
        runcache.SOURCE_ROOT = real
    hone.close()


def check_whole_token_mapping() -> None:
    entry = {"tokens": ["3 May", "ab12f3c"], "sourceRunId": "r_0a1b", "durationMs": 0}
    replay = runcache.Replay(None, entry, runcache.RunInput("", ("4 May", "9f8e7d6")), "r_ffff")  # type: ignore[arg-type]
    mapped = replay.text("On 3 May, not 13 May, run r_0a1b, not r_0a1bc, commit ab12f3c, not ab12f3c0.")
    assert mapped == "On 4 May, not 13 May, run r_ffff, not r_0a1bc, commit 9f8e7d6, not ab12f3c0.", mapped


async def check_corrupt_files_skipped() -> None:
    hone = make_hone("corrupt")
    batch = add_batch(hone, dt.date(2026, 11, 13), "/work/booth")
    d = hone.s.service.data_dir / runcache.RUN_CACHE_DIR
    d.mkdir(parents=True)
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    (d / "binary.json").write_bytes(b"\xff\xfe\x00")
    (d / "shape.json").write_text(json.dumps({"version": runcache.ENTRY_VERSION, "id": "shape"}), encoding="utf-8")
    (d / "noreview.json").write_text(json.dumps({"version": runcache.ENTRY_VERSION, "id": "noreview",
                                                 "fingerprint": "x", "tokens": [], "sourceRunId": "r_1",
                                                 "recordedAt": "2026-11-11T00:00:00Z", "durationMs": 1,
                                                 "outcome": "succeeded", "title": "t", "stages": [],
                                                 "verdicts": [None], "review": None}), encoding="utf-8")
    assert hone.run_cache is not None and hone.run_cache.entries() == [], "bad files are skipped"
    script(batch, first_title="docs: give offer letters a fixed reply deadline")
    run = await finish(hone)
    assert run["status"] == "succeeded", f"a run starts and ends beside bad cache files: {run['status']}"
    assert len(cache_files(hone)) == 5, "and it is recorded"

    broken = make_hone("cache-raises")
    batch = add_batch(broken, dt.date(2026, 11, 13), "/work/booth")
    script(batch, first_title="docs: give offer letters a fixed reply deadline")

    def explode(*args: Any) -> None:
        raise RuntimeError("cache exploded")

    assert broken.run_cache is not None
    broken.run_cache.replay_for = explode  # type: ignore[method-assign]
    logging.getLogger("hone.runcache").disabled = True
    run = await finish(broken)
    logging.getLogger("hone.runcache").disabled = False
    assert run["status"] == "succeeded", f"a failing cache lookup falls back to a real run: {run['status']}"
    assert cache_files(broken) == [], "that run is not recorded"
    hone.close()
    broken.close()


async def check_demo_mode_only() -> None:
    off = make_hone("demo-off", demo=False)
    batch = add_batch(off, dt.date(2026, 11, 13), "/work/booth")
    script(batch, first_title="docs: give offer letters a fixed reply deadline")
    assert (await finish(off))["status"] == "succeeded"
    assert off.run_cache is None and cache_files(off) == [], "outside demo mode nothing is recorded"
    on = make_hone("demo-on")
    batch = add_batch(on, dt.date(2026, 11, 13), "/work/booth")
    script(batch, first_title="docs: give offer letters a fixed reply deadline")
    assert (await finish(on))["status"] == "succeeded"
    assert len(cache_files(on)) == 1, "in demo mode the same run is recorded"
    off.close()
    on.close()


async def check_replay_needs_the_recorded_verdicts() -> None:
    recorded = make_hone("verdicts-a")
    batch = add_batch(recorded, dt.date(2026, 11, 13), "/work/booth-a")
    recorded.close()
    shutil.copytree(ROOT / "verdicts-a", ROOT / "verdicts-b")
    recorded = make_hone("verdicts-a")
    script(batch, first_title="x" * 80)  # attempt 1 is rejected for its long title
    run = await finish(recorded)
    assert run["status"] == "succeeded" and run["attempts"] == 2, run
    [name] = cache_files(recorded)
    entry = json.loads((ROOT / "verdicts-a" / runcache.RUN_CACHE_DIR / name).read_text(encoding="utf-8"))
    assert entry["verdicts"][0] and entry["verdicts"][1] is None, entry["verdicts"]
    SCRIPT.clear()

    again = make_hone("verdicts-b")
    shutil.copytree(ROOT / "verdicts-a" / runcache.RUN_CACHE_DIR, ROOT / "verdicts-b" / runcache.RUN_CACHE_DIR)
    assert again.run_cache is not None
    again.run_cache.set_review(entry["id"], "approved", ["first reviewer", "second reviewer"])
    real_verify = patch.verify_commit_message
    patch.verify_commit_message = lambda result: ("", "")  # the verifier now accepts any title
    try:
        inp = fingerprint(again)
        assert inp.fingerprint == entry["fingerprint"], "the copied batch is the recorded input"
        run_row = {"id": "r_0000", "trace_ids": batch, "base_version_id": again.current_id}
        assert again.run_cache.replay_for(again, run_row, inp) is None, \
            "a recording whose rejected attempt would now pass does not replay"
    finally:
        patch.verify_commit_message = real_verify
    replayed = await finish(again)
    assert replayed["replay"] and replayed["replay"]["entryId"] == entry["id"], "under the same verifier it replays"
    assert replayed["status"] == "succeeded" and replayed["attempts"] == 2, replayed
    assert replayed["result"]["commitTitle"] == run["result"]["commitTitle"]
    recorded.close()
    again.close()


async def main() -> None:
    check_date_formats_and_gaps()
    check_shifted_batch_matches()
    check_source_change()
    check_whole_token_mapping()
    await check_corrupt_files_skipped()
    await check_demo_mode_only()
    await check_replay_needs_the_recorded_verdicts()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print("run cache checks passed")
