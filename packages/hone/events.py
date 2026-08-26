"""Event streams: append-only run events.jsonl plus in-process SSE fan-out.

Every run event lands in /data/runs/<id>/events.jsonl first; SSE subscribers
then read the file from byte zero and tail it — refresh and late join replay
identically, and the cached file doubles as the offline booth replay.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class Bus:
    """Fan-out for global state-change events (dashboard updates without reload)."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)


def append_event(events_path: Path, event: dict[str, Any]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    out = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


async def tail_sse(events_path: Path, subscribe_global=None) -> Any:
    """Yield SSE `data:` payloads: the whole file from byte zero, then tail it."""
    import os

    pos = 0
    idle = 0.0
    while True:
        if events_path.exists():
            size = events_path.stat().st_size
            if size > pos:
                with events_path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read(size - pos)
                    pos += len(chunk)
                text = chunk.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        yield f"data: {line}\n\n"
                continue
        elif pos:
            # File vanished (fresh run id): restart from zero if it reappears.
            pos = 0
        await asyncio.sleep(0.25)
        idle += 0.25
        _ = os  # keep import local cheap
