"""Demo mode in the service (HONE_DEMO=1) rewinds to the prepared scenario.

The prepared state is built once per day by a child process, because the
build's virtual clock patches module globals, and cached under the data dir.
A reset copies it over the live data dir and reopens Hone in place. It keeps
the run cache, so a recorded run of the prepared batch survives every reset.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

from ..runcache import RUN_CACHE_DIR
from ..service import Hone
from .build import META_FILE
from .scenario import WORKSPACE

CACHE_DIR = "demo-cache"
STAGING_IN = ".demo-incoming"
STAGING_OUT = ".demo-outgoing"
KEEP = (CACHE_DIR, RUN_CACHE_DIR, STAGING_IN, STAGING_OUT)


def _scenario_version() -> str:
    """Changes whenever the scenario code or assets change, so an updated
    checkout never serves a prepared state built by older code. Shipped run
    cache entries are not part of the scenario."""
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(p for p in root.rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts and RUN_CACHE_DIR not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


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

    def _settings_version(self) -> str:
        """The prepared sessions and runs name the configured models, so a
        changed config must not reuse a state built under the old one."""
        dumped = self.hone.s.model_dump_json(exclude={"service"})
        return hashlib.sha256(dumped.encode()).hexdigest()[:12]

    async def _prepared(self) -> Path:
        """Today's prepared state, or the one for the configured demo date,
        built on first use and cached for the day."""
        today = self.hone.s.service.demo_date or dt.datetime.now().astimezone().date()
        target = self.cache / f"{today.isoformat()}-{_scenario_version()}-{self._settings_version()}"
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
                    if child.name not in KEEP:
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
