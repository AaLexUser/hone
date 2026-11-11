"""The one process: FastAPI serving the API, the SSE streams, and the UI.

Public read: GET /agents.md and every GET route. Private write: one shared
bearer token on every mutating endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .events import tail_sse
from .config import HoneConfig
from .gitstore import GitError
from .runcache import RunCache
from .service import Hone
from .settings import load_settings

if TYPE_CHECKING:
    from .demo.mode import DemoMode

settings: HoneConfig = load_settings()
hone = Hone(settings)
demo: DemoMode | None = None
if settings.service.demo:
    from .demo.mode import DemoMode

    demo = DemoMode(hone)


async def _warm_demo(mode: DemoMode) -> None:
    try:
        await mode.prepared()
    except Exception:  # the reset retries the build and reports the error
        logging.getLogger("hone.demo").exception("building the demo scenario failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Build today's prepared state at startup, so the first reset is quick.
    warm = asyncio.create_task(_warm_demo(demo)) if demo is not None else None
    yield
    if warm is not None:
        warm.cancel()


app = FastAPI(title="Hone", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------- auth

async def require_write(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {settings.service.token}":
        raise HTTPException(status_code=401, detail="hone bearer token required")


# ----------------------------------------------------------------- public

@app.get("/agents.md")
def agents_md() -> PlainTextResponse:
    body = hone.dirs.read_current()
    return PlainTextResponse(
        body,
        media_type="text/markdown",
        headers={
            "x-hone-version": hone.current_id,
            "cache-control": "no-store",
        },
    )


@app.get("/api/ui-config")
def ui_config() -> dict[str, Any]:
    return {
        "writeToken": settings.service.token if settings.service.expose_write_token else None,
        "model": settings.target.model.split("/")[-1],
    }


@app.get("/api/state")
def state() -> dict[str, Any]:
    return hone.state_payload()


@app.get("/api/traces/{session_id}")
def trace_detail(session_id: str) -> dict[str, Any]:
    t = hone.db.one("SELECT * FROM traces WHERE session_id = ?", (session_id,))
    if not t:
        raise HTTPException(status_code=404, detail="trace not found")
    p = hone.dirs.trace_path(session_id)
    turns = _parse_conversation(p.read_text(encoding="utf-8")) if p.exists() else []
    return {
        "id": t["session_id"],
        "firstLine": t["first_line"],
        "receivedAt": t["received_at"],
        "turns": t["turns"],
        "feedback": t["feedback"],
        "status": t["status"],
        "versionId": t["version_id"],
        "conversation": turns,
    }


@app.get("/api/traces/{session_id}/jsonl")
def trace_jsonl(session_id: str) -> Response:
    p = hone.dirs.trace_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="trace jsonl not found")
    return PlainTextResponse(
        p.read_text(encoding="utf-8"),
        media_type="application/jsonl",
        headers={"content-disposition": f'attachment; filename="{session_id}.jsonl"'},
    )


def _run_camel(r: dict[str, Any]) -> dict[str, Any]:
    """DB row → the camelCase run record the UI renders."""
    result = r.get("result") or {}
    return {
        "id": r["id"],
        "status": r["status"],
        "trigger": r["trigger"],
        "startedAt": r["started_at"],
        "endedAt": r.get("ended_at"),
        "durationMs": r.get("duration_ms") or 0,
        "model": r["model"],
        "attempts": r.get("attempts", 1),
        "traceIds": r.get("trace_ids", []),
        "baseVersionId": r["base_version_id"],
        "resultVersionId": r.get("result_version_id"),
        "note": r.get("note"),
        "changes": r.get("changes", []),
        "commitTitle": result.get("commitTitle"),
        "commitBody": result.get("commitBody"),
        "commitBranch": result.get("commitBranch"),
    }


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return [_run_camel(r) for r in hone.runs_payload()]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    r = hone.run_payload(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    out = _run_camel(r)
    out["hasReport"] = hone.dirs.report_path(run_id).exists()
    # Set when the run replayed an approved run-cache entry. The page never shows it.
    out["replayOf"] = r["replay"]
    return out


@app.get("/api/runs/{run_id}/report")
def run_report(run_id: str) -> Response:
    """The review judge's HTML report, rendered in the run page."""
    if not hone.db.run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    p = hone.dirs.report_path(run_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="no report for this run")
    return Response(
        p.read_text(encoding="utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"cache-control": "no-store", "content-security-policy": "sandbox"},
    )


@app.get("/api/runs/{run_id}/review")
def run_review(run_id: str) -> Response:
    """The review judge's structured findings, the data behind report.html."""
    if not hone.db.run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    p = hone.dirs.review_path(run_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="no review for this run")
    return Response(p.read_text(encoding="utf-8"), media_type="application/json")


@app.get("/api/versions")
def versions() -> dict[str, Any]:
    payload = hone.state_payload()
    return {
        "versions": payload["versions"],
        "currentId": payload["currentId"],
        "currentBranch": payload["currentBranch"],
        "branches": payload["branches"],
    }


@app.get("/api/log-edits")
def log_edits() -> dict[str, Any]:
    """The optimizer's experience history: one entry per completed run."""
    return hone.log_edits_payload()


# -------------------------------------------------------------- mutations

@app.put("/api/traces/{session_id}", dependencies=[Depends(require_write)])
async def put_trace(session_id: str, request: Request) -> dict[str, Any]:
    body = await request.body()
    version = request.headers.get("x-hone-version")
    trace = hone.upsert_trace(session_id, body, version)
    return {"ok": True, "trace": trace}


@app.post("/api/traces/{session_id}/feedback", dependencies=[Depends(require_write)])
async def post_feedback(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Set the session's feedback. A session holds one, so this replaces any earlier one."""
    text = (payload or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="feedback text required")
    if not hone.set_feedback(session_id, text):
        raise HTTPException(status_code=404, detail="trace not found")
    return {"ok": True}


@app.delete("/api/traces/{session_id}/feedback", dependencies=[Depends(require_write)])
async def delete_feedback(session_id: str) -> dict[str, Any]:
    if not hone.set_feedback(session_id, None):
        raise HTTPException(status_code=404, detail="trace not found")
    return {"ok": True}


@app.post("/api/traces/reset", dependencies=[Depends(require_write)])
async def reset_traces(payload: dict[str, Any]) -> dict[str, Any]:
    """Return traces to 'new' so the optimizer can produce another candidate
    over the same batch (multi-candidate optimization)."""
    ids = payload.get("ids") or []
    all_new = bool(payload.get("all"))
    if not all_new and not ids:
        raise HTTPException(status_code=422, detail="ids or all=true required")
    if all_new:
        cur = hone.db.execute("UPDATE traces SET status = 'new', analyzed_by = NULL")
        n = cur.rowcount if cur is not None else 0
    else:
        n = 0
        for sid in ids:
            cur = hone.db.execute(
                "UPDATE traces SET status = 'new', analyzed_by = NULL WHERE session_id = ?", (sid,)
            )
            n += cur.rowcount if cur is not None else 0
    hone.bus.publish({"type": "traces_reset", "count": n})
    return {"ok": True, "reset": n}


@app.post("/api/config", dependencies=[Depends(require_write)])
async def post_config(payload: dict[str, Any]) -> dict[str, Any]:
    hone.set_config(
        batch_size=payload.get("batchSize"),
        auto_optimize=payload.get("autoOptimize"),
    )
    return {"ok": True}


@app.post("/api/optimize", dependencies=[Depends(require_write)])
async def post_optimize(request: Request) -> dict[str, Any]:
    raw = await request.body()
    body: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            body = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            body = {}
    try:
        return hone.start_run(
            trigger="manual",
            set_current=body.get("setCurrent", True),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/versions/{node_id}/current", dependencies=[Depends(require_write)])
async def post_current(node_id: str) -> dict[str, Any]:
    if not hone.set_current(node_id):
        raise HTTPException(status_code=404, detail="version not found")
    return {"ok": True, "currentId": node_id}


@app.post("/api/branches", dependencies=[Depends(require_write)])
async def post_branch(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload or {}).get("name", "")
    from_node = (payload or {}).get("fromNode")
    try:
        out = hone.create_branch(name, from_node)
    except GitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **out}


@app.post("/api/branches/rename", dependencies=[Depends(require_write)])
async def post_branch_rename(payload: dict[str, Any]) -> dict[str, Any]:
    old = (payload or {}).get("from", "")
    new = (payload or {}).get("to", "")
    if not old:
        raise HTTPException(status_code=422, detail="from required")
    try:
        out = hone.rename_branch(old, new)
    except GitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **out}


@app.post("/api/branches/{name}/merge", dependencies=[Depends(require_write)])
async def post_branch_merge(name: str) -> dict[str, Any]:
    try:
        out = hone.merge_branch(name)
    except GitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **out}


@app.post("/api/runs/{run_id}/pipeline-event", dependencies=[Depends(require_write)])
async def pipeline_event(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    await hone.record_pipeline_event(run_id, payload)
    return {"ok": True}


# -------------------------------------------------------------- run cache

def _run_cache() -> RunCache:
    if hone.run_cache is None:
        raise HTTPException(status_code=404, detail="the run cache is on only in demo mode (HONE_DEMO=1)")
    return hone.run_cache


def _cache_summary(cache: RunCache, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "fingerprint": entry["fingerprint"],
        "sourceRunId": entry["sourceRunId"],
        "recordedAt": entry["recordedAt"],
        "durationMs": entry["durationMs"],
        "outcome": entry["outcome"],
        "title": entry["title"],
        "review": entry["review"],
        "local": cache.is_local(entry["id"]),
    }


@app.get("/api/run-cache", dependencies=[Depends(require_write)])
def run_cache_list() -> list[dict[str, Any]]:
    """Recorded real runs, newest first. Only approved entries replay."""
    cache = _run_cache()
    return [_cache_summary(cache, e) for e in cache.entries()]


@app.get("/api/run-cache/{entry_id}", dependencies=[Depends(require_write)])
def run_cache_entry(entry_id: str) -> dict[str, Any]:
    """The whole entry, as it is saved under packages/hone/demo/run-cache/ to ship it."""
    entry = _run_cache().get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no such run-cache entry")
    return dict(entry)


@app.post("/api/run-cache/{entry_id}/review", dependencies=[Depends(require_write)])
async def run_cache_review(entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Body {"status": "approved" | "rejected" | "candidate", "notes": ["..."]}.
    Approving needs the reviewers' notes, see docs/run-review.md."""
    cache = _run_cache()
    status = payload.get("status")
    notes = payload.get("notes") or []
    if status not in ("approved", "rejected", "candidate"):
        raise HTTPException(status_code=422, detail="status must be approved, rejected or candidate")
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise HTTPException(status_code=422, detail="notes must be a list of strings")
    try:
        entry = cache.set_review(entry_id, status, notes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such run-cache entry") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _cache_summary(cache, entry)


# ------------------------------------------------------------------- demo

@app.get("/api/demo")
def demo_status() -> dict[str, Any]:
    return {"enabled": demo is not None}


@app.post("/api/demo/reset", dependencies=[Depends(require_write)])
async def demo_reset(request: Request) -> Response:
    """Restore the prepared scenario. Returns the manifest with the project
    folder's files (base64) and the prepared chats as Pi session JSONL, oldest first.
    An optional JSON body {"workspace": "/abs/folder"} puts the real folder
    into Hone's copy of the sessions."""
    from .demo.mode import DemoError

    if demo is None:
        raise HTTPException(status_code=404, detail="demo mode is off (start Hone with HONE_DEMO=1)")
    raw = await request.body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="the body must be JSON") from exc
    workspace = body.get("workspace") if isinstance(body, dict) else None
    try:
        manifest = await demo.reset(workspace if isinstance(workspace, str) and workspace else None)
    except DemoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(manifest, media_type="application/json")


# -------------------------------------------------------------------- SSE

@app.get("/api/events")
async def global_events() -> StreamingResponse:
    q = hone.bus.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'hello', 'state': hone.state_payload()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hone.bus.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    if not hone.db.run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    events_path = hone.dirs.events_path(run_id)

    async def gen():
        async for line in tail_sse(events_path):
            yield line

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


# -------------------------------------------------------------------- UI

_ui_dir = Path(settings.service.ui_dir)
_index_html = _ui_dir / "index.html"
if _index_html.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException) -> Response:
        """Deep links (/runs/x, /versions) fall back to index.html, not 404."""
        if (
            exc.status_code == 404
            and not request.url.path.startswith("/api")
            and not request.url.path.startswith("/agents.md")
            and "text/html" in request.headers.get("accept", "")
            and _index_html.exists()
        ):
            return FileResponse(str(_index_html))
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ parse

def _parse_conversation(text: str) -> list[dict[str, Any]]:
    """Pi session JSONL → the turn shape the trace page renders."""
    turns: list[dict[str, Any]] = []
    pending_tools: dict[str, dict[str, Any]] = {}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") if entry.get("type") == "message" else entry
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            text_out = content if isinstance(content, str) else _blocks_text(content)
            if text_out.strip():
                turns.append({"role": "user", "text": text_out.strip()[:4000]})
        elif role == "assistant":
            text_out = _blocks_text(content)
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    pending_tools[block.get("id")] = {
                        "role": "tool",
                        "text": "",
                        "tool": {
                            "name": block.get("name", "tool"),
                            "args": _short(block.get("arguments")),
                            "result": "",
                        },
                    }
            if text_out.strip():
                turns.append({"role": "assistant", "text": text_out.strip()[:4000]})
        elif role == "toolResult":
            call = pending_tools.pop(msg.get("toolCallId"), None)
            if call:
                call["tool"]["result"] = _blocks_text(content)[:1000]
                turns.append(call)
    return turns


def _blocks_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _short(value: Any) -> str:
    if isinstance(value, dict):
        value = " ".join(f"{k}={v}" for k, v in value.items())
    s = str(value)
    return s[:200]
