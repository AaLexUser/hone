"""Demo mode in the service (HONE_DEMO=1): rewind to the prepared scenario,
and replay its next run through Hone's own run loop.

The prepared state is built once per day by a child process, because the
build's virtual clock patches module globals, and cached under the data dir.
A reset copies it over the live data dir and reopens Hone in place.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ..service import Hone
from .build import META_FILE, SEED
from .scenario import WORKSPACE
from .scripted import Clock, Director
from .stories import STORIES

CACHE_DIR = "demo-cache"
STAGING_IN = ".demo-incoming"
STAGING_OUT = ".demo-outgoing"
# Script time runs this many times faster than the run it stands for, so the
# prepared run (about 13 minutes of script time) plays in about a minute.
REPLAY_SPEED = 13.0
REPLAY = STORIES["live"]


class DemoError(RuntimeError):
    """A demo action that cannot run now. The message is for the presenter."""


class DemoMode:
    def __init__(self, hone: Hone) -> None:
        self.hone = hone
        self.data_dir = hone.s.service.data_dir
        self.cache = self.data_dir / CACHE_DIR
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ prepared

    async def prepared(self) -> Path:
        async with self._lock:
            return await self._prepared()

    async def _prepared(self) -> Path:
        """Today's prepared state, built on first use and cached for the day."""
        today = dt.datetime.now().astimezone().date()
        target = self.cache / today.isoformat()
        if (target / "manifest.json").exists():
            return target
        staging = self.cache / f"building-{today.isoformat()}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "hone.demo", "build", "--out", str(staging), "--date", today.isoformat(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await proc.communicate()
        if proc.returncode != 0:
            tail = output.decode("utf-8", errors="replace").strip().splitlines()[-1:]
            raise DemoError(f"building the demo scenario failed: {' '.join(tail) or proc.returncode}")
        staging.rename(target)
        for old in self.cache.iterdir():
            if old != target:
                shutil.rmtree(old, ignore_errors=True)
        return target

    # --------------------------------------------------------------- reset

    async def reset(self, workspace: str | None = None) -> bytes:
        """Restore the prepared state and return the manifest as JSON bytes.
        `workspace`, when given, replaces the placeholder in Hone's copy of the
        sessions so trace pages show the real project folder."""
        async with self._lock:
            prepared = await self._prepared()

            if not self._owns_data_dir():
                raise DemoError(f"refusing to reset {self.data_dir}: it holds a real Hone history. "
                                "Run the demo on its own HONE_DATA_DIR.")

            def rewrite() -> None:
                incoming = self.data_dir / STAGING_IN
                outgoing = self.data_dir / STAGING_OUT
                for stale in (incoming, outgoing):
                    shutil.rmtree(stale, ignore_errors=True)
                shutil.copytree(prepared / "data", incoming)
                if workspace:
                    escaped = json.dumps(workspace)[1:-1]
                    for trace in (incoming / "traces").glob("*.jsonl"):
                        trace.write_text(trace.read_text(encoding="utf-8").replace(WORKSPACE, escaped),
                                         encoding="utf-8")
                # Until the swap below, a failure leaves the old state whole.
                outgoing.mkdir()
                for child in list(self.data_dir.iterdir()):
                    if child.name not in (CACHE_DIR, STAGING_IN, STAGING_OUT):
                        child.rename(outgoing / child.name)
                for child in list(incoming.iterdir()):
                    child.rename(self.data_dir / child.name)
                incoming.rmdir()
                shutil.rmtree(outgoing, ignore_errors=True)

            await self.hone.reopen(rewrite)
        self.hone.bus.publish({"type": "demo_reset"})
        return (prepared / "manifest.json").read_bytes()

    def _owns_data_dir(self) -> bool:
        """A data dir is the demo's to replace once a reset has written its
        marker, or while it holds no traces and no runs."""
        if (self.data_dir / META_FILE).exists():
            return True
        return not self.hone.db.traces() and not self.hone.db.query("SELECT id FROM runs LIMIT 1")

    # -------------------------------------------------------------- replay

    def _meta(self) -> dict[str, Any] | None:
        path = self.data_dir / META_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def replay_ready(self) -> bool:
        """True while the prepared run has not played since the last reset."""
        meta = self._meta()
        if meta is None or self._lock.locked() or self.hone.active_run():
            return False
        status = {t["session_id"]: t["status"] for t in self.hone.db.traces()}
        if any(status.get(meta["traces"].get(key)) != "new" for key in REPLAY.batch):
            return False
        return REPLAY.final.edits[0].old in self.hone.dirs.read_current()

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "replayReady": self.replay_ready()}

    def replay(self) -> dict[str, Any]:
        """Play the prepared run over the whole unanalyzed batch, so live
        sessions from the booth join the prepared ones."""
        if not self.replay_ready():
            raise DemoError("the prepared run is not ready, reset the demo first")
        meta = self._meta()
        assert meta is not None
        fresh = [t for t in self.hone.db.traces() if t["status"] == "new"]
        director = Director(self.hone, Clock(speed=REPLAY_SPEED), REPLAY, meta["traces"], SEED)
        return self.hone.start_run(trigger="manual", batch_size=len(fresh), executor_factory=director.executor)
