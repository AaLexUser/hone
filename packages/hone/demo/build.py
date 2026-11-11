"""Build the prepared demo state for one day, in a throwaway process.

The output dir holds three things built from the same hire table.

- `data/` is a Hone data dir with the sessions, feedback and three runs, and
  `data/demo.json` maps each hire to its trace id.
- `project/` is the project folder. Office inputs sit in `Inbox/`, the letters
  the chats produced sit at the top level.
- `manifest.json` is what `POST /api/demo/reset` returns.

The build drives Hone's own run loop under a virtual clock that patches module
globals, so it must never run inside the service process.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import random
import shutil
from pathlib import Path
from typing import Any

from .. import ids
from ..config import HoneConfig
from ..service import Hone
from .office import (
    TEMPLATE_ASSET,
    Workspace,
    check_tools,
    fill_script,
    letter_values,
    write_approval,
)
from .scenario import (
    ARCHIVE_HIRE,
    ARCHIVE_LETTER,
    HIRES,
    LIVE_HIRE,
    PROJECT_TITLE,
    TEMPLATE,
    approval_ref,
    hire_dates,
    last_prepared_day,
    local_ms,
    workdays_back,
)
from .scripted import Clock, Director
from .sessions import offer_session, uuid7
from .stories import RUNS, STORIES

SEED = 7
BATCH_SIZE = 4
META_FILE = "demo.json"


def prepared_settings(settings: HoneConfig, data_dir: Path) -> HoneConfig:
    return settings.model_copy(update={
        "service": settings.service.model_copy(update={"data_dir": data_dir.resolve()}),
    })


def write_archive(ws: Workspace, end: dt.date) -> None:
    """Ben Harris's letter, written in the house style before the agent."""
    h = ARCHIVE_HIRE
    letter = workdays_back(end, 25)
    start = letter + dt.timedelta(days=35 - letter.weekday())
    (ws.root / "Archive").mkdir(exist_ok=True)
    script = fill_script(letter_values(h, approval_ref(-30, letter.year), start, h.manager or ""),
                         out=ARCHIVE_LETTER, relocation=False, us_dates=False, collapse=False, delete_blocks=True)
    ws.write_tmp("archive.py", script)
    for command in ("python3 /tmp/archive.py", f"soffice --headless --convert-to pdf --outdir Archive {ARCHIVE_LETTER}"):
        output, failed = ws.bash(command, letter)
        if failed:
            raise RuntimeError(f"archive letter failed: {output}")


async def build(out: Path, settings: HoneConfig, today: dt.date) -> None:
    check_tools()
    end = last_prepared_day(today)
    data_dir, project = out / "data", out / "project"
    for d in (data_dir, project):
        if d.exists():
            shutil.rmtree(d)
    ws = Workspace(project, out / "scratch")
    (project / "Inbox").mkdir(parents=True)
    shutil.copyfile(TEMPLATE_ASSET, project / TEMPLATE)
    write_archive(ws, end)

    clock = Clock(start_ms=local_ms(workdays_back(end, 11), "08:30"))
    clock.install()
    rng = random.Random(f"{SEED}:runs")
    run_ids = iter(dict.fromkeys(f"r_{rng.getrandbits(16):04x}" for _ in range(16)))
    ids.new_run_id = lambda: next(run_ids)

    hone = Hone(prepared_settings(settings, data_dir))
    hone.set_config(batch_size=BATCH_SIZE, auto_optimize=False)
    trace_ids: dict[str, str] = {}
    chats: list[dict[str, Any]] = []

    agenda: list[tuple[int, str, Any]] = [
        (local_ms(workdays_back(end, h.workday), h.clock), "trace", (n, h)) for n, h in enumerate(HIRES)]
    agenda += [(local_ms(workdays_back(end, day), hhmm), "run", (key, trigger)) for key, day, hhmm, trigger in RUNS]
    for at, kind, item in sorted(agenda, key=lambda x: x[0]):
        clock.set(max(at, clock.now_ms()))
        if kind == "trace":
            n, h = item
            dates = hire_dates(h, end)
            write_approval(project / h.approval, h, approval_ref(n, dates.letter.year), dates.approved, dates.start)
            agents_md = hone.dirs.read_current()
            (project / "AGENTS.md").write_text(agents_md, encoding="utf-8")
            trng = random.Random(f"{SEED}:{h.key}")
            session_id = uuid7(clock.now_ms(), trng)
            session = offer_session(h, n, session_id, clock.now_ms(), agents_md, ws, end, settings.target.model, trng)
            clock.set(session.t + trng.randint(1500, 4000))
            trace = hone.upsert_trace(session_id, session.body(), hone.current_id)
            trace_ids[h.key] = trace["id"]
            if h.feedback:
                clock.set(clock.now_ms() + trng.randint(60_000, 240_000))
                hone.set_feedback(trace["id"], h.rated_feedback)
            chats.append({"title": f"Offer letter for {h.name}", "sessionId": session_id,
                          "traceId": trace["id"], "feedback": h.rated_feedback, "jsonl": session.body().decode("utf-8")})
        else:
            key, trigger = item
            director = Director(hone, clock, STORIES[key], trace_ids, SEED)
            hone.start_run(trigger=trigger, executor_factory=director.executor)
            task = hone._run_task
            assert task is not None
            await task
    hone.close()

    write_approval(project / LIVE_HIRE.approval, LIVE_HIRE, approval_ref(len(HIRES), end.year),
                   end, hire_dates(LIVE_HIRE, end).start)
    (project / "AGENTS.md").write_text((data_dir / "repo" / "AGENTS.md").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    (data_dir / META_FILE).write_text(json.dumps({"date": today.isoformat(), "traces": trace_ids}, indent=2) + "\n",
                                      encoding="utf-8")
    manifest = {
        "project": {"title": PROJECT_TITLE},
        "files": [{"path": p.relative_to(project).as_posix(), "base64": base64.b64encode(p.read_bytes()).decode()}
                  for p in ws.files()],
        "chats": chats,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(out / "scratch")


def run(out: Path, settings: HoneConfig, today: dt.date) -> None:
    asyncio.run(build(out, settings, today))
