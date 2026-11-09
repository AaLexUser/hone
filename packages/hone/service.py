"""Domain orchestration: the loop from settled Pi sessions to a served AGENTS.md.

One Hone instance owns SQLite, /data (traces, runs, and the Git repo that now
tracks AGENTS.md), the event bus, and at most one live optimizer run (one Harbor
job at a time).

The version graph IS Git: every applied optimizer iteration is a commit whose
message the MAJICS judge authored, branches are real branches, and "current"
is HEAD of the repo at /data/repo. Every completed run is also recorded in
/data/log_edits.json — the experience history the next optimizer run reviews.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import ids, logedits, patch
from .config import HoneConfig
from .db import Db
from .events import Bus, append_event, read_events
from .gitstore import (
    AUTO_BRANCH_PREFIX,
    OPTIMIZER_AUTHOR,
    TRUNK,
    GitError,
    GitRepo,
    valid_branch_name,
)
from .store import SEED_AGENTS_MD, SEED_COMMIT_BODY, SEED_COMMIT_TITLE, DataDirs

if TYPE_CHECKING:
    from .majics.pipeline import ExecutorFactory

# Branch colors from the brand book: trunk first, brand set for the next five,
# then a deterministic golden-angle walk for any branch beyond that — every new
# branch gets a unique color
BRANCH_COLORS = ["#6672e0", "#2fbcb0", "#d99a3c", "#b06ee8", "#4aa3f0", "#e5736e"]


def branch_color(lane: int) -> str:
    if lane < len(BRANCH_COLORS):
        return BRANCH_COLORS[lane]
    hue = (137.508 * lane + 96) % 360
    return f"hsl({hue:.0f}, 68%, 62%)"


def _now_ms() -> int:
    return int(time.time() * 1000)


# Lane colors for the pipeline agents in the UI — the brand branch palette
# (kept in sync with the in-sandbox driver's roster).
_AGENT_COLORS = ["#2fbcb0", "#d99a3c", "#b06ee8", "#4aa3f0", "#e5736e"]


def _roster_payload(s: HoneConfig) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    config = s.majics
    for i, seat in enumerate(config.review.panel):
        agents.append({"key": f"review-{i + 1}", "model": config.seat_label(seat), "role": "reviewer",
                       "stage": "review", "color": _AGENT_COLORS[i % len(_AGENT_COLORS)]})
    agents.append({"key": "review-judge", "model": config.seat_label(config.review.judge),
                   "role": "judge", "stage": "review", "color": "#6672e0"})
    for i, seat in enumerate(config.propose.panel):
        agents.append({"key": f"propose-{i + 1}", "model": config.seat_label(seat), "role": "proposer",
                       "stage": "propose", "color": _AGENT_COLORS[(i + 2) % len(_AGENT_COLORS)]})
    agents.append({"key": "propose-judge", "model": config.seat_label(config.propose.judge),
                   "role": "judge", "stage": "propose", "color": "#6672e0"})
    return agents


class Hone:
    def __init__(self, settings: HoneConfig) -> None:
        self.s = settings
        self.bus = Bus()
        self._open()

    def _open(self) -> None:
        self.dirs = DataDirs(self.s.service.data_dir)
        self.git = GitRepo(self.dirs.repo)
        self.db = Db(self.s.service.data_dir / "app.sqlite")
        self._run_task: asyncio.Task | None = None
        self._live: dict[str, dict[str, Any]] = {}
        self._bootstrap()

    async def reopen(self, rewrite: Callable[[], None]) -> None:
        """Stop the live run, close the store, let `rewrite` replace the data
        dir, and open it again. The bus and its subscribers stay."""
        task = self._run_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})
        self.close()
        try:
            rewrite()
        finally:
            self._open()

    # ------------------------------------------------------------------ boot

    def _bootstrap(self) -> None:
        if self.db.get_config("batch_size") is None:
            self.db.set_config("batch_size", 8)
        if self.db.get_config("auto_optimize") is None:
            self.db.set_config("auto_optimize", False)
        logedits.ensure(self.dirs.log_edits)
        self._bootstrap_git()
        # A run left mid-flight by a restart is closed out — nothing was applied.
        for r in self.db.query("SELECT id, base_version_id, trace_ids FROM runs WHERE status IN ('running','validating')"):
            append_event(
                self.dirs.events_path(r["id"]),
                {"at": 0, "kind": "log", "icon": "fail", "text": "Run interrupted by service restart",
                 "detail": f"AGENTS.md stays at {r['base_version_id']}", "level": "error"},
            )
            self.db.update_run(
                r["id"],
                status="failed",
                ended_at=_now_ms(),
                duration_ms=None,
                note="Interrupted by a service restart before the optimizer finished. "
                     f"AGENTS.md was left at {r['base_version_id']}.",
            )
            # Release the frozen batch back to the pool of unanalyzed traces.
            for sid in json.loads(r["trace_ids"]):
                self.db.execute(
                    "UPDATE traces SET analyzed_by = NULL WHERE session_id = ? AND status = 'new'", (sid,)
                )

    # ---------------------------------------------------------- git bootstrap

    def _bootstrap_git(self) -> None:
        """First boot seeds the repo; every boot resyncs the index from git."""
        self.git.ensure()
        if not self.git.has_commits():
            self._seed_repo()
        self._sync_index_from_git()
        # Head of the repo is the served version; heal drift after external git use.
        current = self.db.get_config("current_id")
        head = self.git.head_short()
        if not current or not self.git.rev_exists(current):
            current = head
            self.db.set_config("current_id", current)
        if head != current:
            self.git.checkout_branch_or_detach(current)

    def _seed_repo(self) -> None:
        sha = self.git.commit_worktree(SEED_AGENTS_MD, SEED_COMMIT_TITLE, SEED_COMMIT_BODY,
                                       trailers={"Hone-Branch": TRUNK})
        self.db.set_config("current_id", sha)

    def _sync_index_from_git(self) -> None:
        """Git is the source of truth; the nodes table is its UI index.
        Commit trailers record where a commit was made — renames (immutable
        trailers) are re-applied so the index matches current branch names."""
        commits = self.git.log_all()
        old_rows = {r["id"]: r for r in self.db.nodes()}
        renames = dict(self.db.get_config("branch_renames") or {})
        lanes = self._branch_lanes(commits)
        rows = []
        for c in commits:
            sha = str(c["sha"])
            old = old_rows.get(sha, {})
            branch = str(c["trailers"].get("Hone-Branch") or old.get("branch") or TRUNK)
            branch = renames.get(branch, branch)
            rows.append({
                "id": sha,
                "parent_id": (c["parents"] or [None])[0] if c["parents"] else None,  # type: ignore[list-item]
                # Keep the millisecond timestamp from insert time; git only
                # stores seconds, which would tie commits made in the same
                # second and destabilize the UI's git-graph ordering.
                "created_at": old.get("created_at") or c["at"],
                "run_id": str(c["trailers"].get("Hone-Run") or old.get("run_id") or "") or None,
                "branch": branch,
                "lane": lanes.get(branch, 0),
                "parents": c["parents"],
                "title": c["title"],
            })
        self.db.replace_all_nodes(rows)

    def _branch_lanes(self, commits: list[dict[str, Any]] | None = None) -> dict[str, int]:
        """Stable lane per branch: trunk first, then order of first appearance."""
        lanes: dict[str, int] = dict(self.db.get_config("branch_lanes") or {})
        lanes.setdefault(TRUNK, 0)
        if TRUNK in lanes and lanes[TRUNK] != 0:
            shifted = {b: (0 if b == TRUNK else l) for b, l in lanes.items()}
            lanes = shifted
        names = [b["name"] for b in self.git.branches()]
        for c in commits or []:
            b = c["trailers"].get("Hone-Branch")
            if b and b not in names:
                names.append(b)
        for name in names:
            if name not in lanes:
                lanes[name] = max(lanes.values()) + 1 if lanes else 0
        self.db.set_config("branch_lanes", lanes)
        return lanes

    def close(self) -> None:
        self.db.close()

    # ----------------------------------------------------------------- read

    @property
    def current_id(self) -> str:
        return self.db.get_config("current_id")

    def current_file_lines(self) -> list[str]:
        return self.dirs.read_current().splitlines()

    def node_file(self, node_id: str) -> list[str]:
        return self.git.file_at(node_id).splitlines()

    def state_payload(self) -> dict[str, Any]:
        active = self.active_run()
        versions = []
        for n in self.db.nodes():
            versions.append(
                {
                    "id": n["id"],
                    "parentId": n["parents"][0] if n["parents"] else None,
                    "parents": n["parents"],
                    "createdAt": n["created_at"],
                    "runId": n["run_id"],
                    "file": self.node_file(n["id"]),
                    "branch": n["branch"],
                    "lane": n["lane"],
                    "title": n.get("title"),
                }
            )
        traces = [
            {
                "id": t["session_id"],
                "firstLine": t["first_line"],
                "receivedAt": t["received_at"],
                "turns": t["turns"],
                "feedback": t["feedback"],
                "status": t["status"],
                "versionId": t["version_id"],
            }
            for t in self.db.traces()
        ]
        return {
            "traces": traces,
            "versions": versions,
            "currentId": self.current_id,
            "currentBranch": self.git.current_branch(),
            "batchSize": self.db.get_config("batch_size"),
            "autoOptimize": self.db.get_config("auto_optimize"),
            "run": active,
            "branches": self.branches_payload(),
            "model": self.s.pipeline_label,
        }

    def branches_payload(self) -> list[dict[str, Any]]:
        lanes = self._branch_lanes()
        current = self.git.current_branch()
        counts: dict[str, int] = {}
        for n in self.db.nodes():
            counts[n["branch"]] = counts.get(n["branch"], 0) + 1
        out = []
        for b in self.git.branches():
            lane = lanes.get(b["name"], 0)
            out.append({
                "name": b["name"],
                "tip": b["tip"],
                "lane": lane,
                "color": branch_color(lane),
                "count": counts.get(b["name"], 0),
                "current": b["name"] == current,
            })
        return out

    def log_edits_payload(self) -> dict[str, Any]:
        return logedits.read_log(self.dirs.log_edits)

    def active_run(self) -> dict[str, Any] | None:
        r = self.db.one(
            "SELECT * FROM runs WHERE status IN ('running','validating') ORDER BY started_at DESC LIMIT 1"
        )
        if not r:
            return None
        r["trace_ids"] = json.loads(r["trace_ids"])
        return r

    def run_payload(self, run_id: str) -> dict[str, Any] | None:
        r = self.db.run(run_id)
        if not r:
            return None
        result = self._read_result(run_id)
        return {**r, "changes": (result or {}).get("changes", []), "result": result}

    def runs_payload(self) -> list[dict[str, Any]]:
        out = []
        for r in self.db.runs():
            result = self._read_result(r["id"])
            out.append({**r, "changes": (result or {}).get("changes", [])})
        return out

    def _read_result(self, run_id: str) -> dict[str, Any] | None:
        p = self.dirs.result_path(run_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    # ---------------------------------------------------------------- write

    def upsert_trace(self, session_id_raw: str, body: bytes, version_id: str | None) -> dict[str, Any]:
        """Store a settled Pi session. Re-publishing the same session upserts."""
        session_id = ids.trace_id_from_session(session_id_raw)
        first_line, turns, stored_version = _summarize_jsonl(body)
        existing = self.db.one("SELECT * FROM traces WHERE session_id = ?", (session_id,))
        trace = {
            "session_id": session_id,
            "first_line": first_line,
            "received_at": _now_ms(),
            "turns": turns,
            "feedback": existing["feedback"] if existing else None,
            "status": existing["status"] if existing else "new",
            "version_id": version_id or stored_version or self.current_id,
            "analyzed_by": existing["analyzed_by"] if existing else None,
        }
        self.dirs.write_trace(session_id, body)
        self.db.upsert_trace(trace)
        arrived = existing is None
        payload = {
            "id": trace["session_id"],
            "firstLine": trace["first_line"],
            "receivedAt": trace["received_at"],
            "turns": trace["turns"],
            "feedback": trace["feedback"],
            "status": trace["status"],
            "versionId": trace["version_id"],
        }
        self.bus.publish({"type": "trace_arrived", "trace": payload, "arrived": arrived})
        self._maybe_auto_optimize()
        return payload

    def add_feedback(self, session_id: str, text: str) -> bool:
        ok = self.db.set_trace_feedback(session_id, text.strip())
        if ok:
            self.bus.publish({"type": "trace_feedback", "sessionId": session_id, "feedback": text.strip()})
        return ok

    def set_config(self, *, batch_size: int | None = None, auto_optimize: bool | None = None) -> None:
        if batch_size is not None:
            self.db.set_config("batch_size", max(1, min(64, int(batch_size))))
        if auto_optimize is not None:
            self.db.set_config("auto_optimize", bool(auto_optimize))
        self.bus.publish({"type": "config_changed"})

    # ------------------------------------------------------------ git writes

    def set_current(self, node_id: str) -> bool:
        """Serve a different version: git checkout of the branch tip, or the commit."""
        node = self.db.node(node_id)
        if not node:
            return False
        self.git.checkout_branch_or_detach(node_id)
        self.db.set_config("current_id", node_id)
        self.bus.publish({"type": "current_changed", "currentId": node_id})
        self.bus.publish({"type": "git_changed", "what": "checkout"})
        return True

    def create_branch(self, name: str, from_node: str | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not valid_branch_name(name):
            raise GitError(f"'{name}' is not a valid branch name")
        at = from_node or self.current_id
        if not self.db.node(at):
            raise GitError(f"unknown version {at}")
        self.git.create_branch(name, at)
        self._branch_lanes()  # assign the new branch a lane
        self._sync_index_from_git()
        self.bus.publish({"type": "branch_created", "branch": name, "at": at})
        self.bus.publish({"type": "git_changed", "what": "branch_created"})
        return {"name": name, "tip": self.git.branch_tip(name)}

    def rename_branch(self, old: str, new: str) -> dict[str, Any]:
        new = (new or "").strip()
        if not self.git.branch_tip(old):
            raise GitError(f"branch '{old}' does not exist")
        if not valid_branch_name(new):
            raise GitError(f"'{new}' is not a valid branch name")
        self.git.rename_branch(old, new)
        lanes = dict(self.db.get_config("branch_lanes") or {})
        if old in lanes:
            lanes[new] = lanes.pop(old)
        self.db.set_config("branch_lanes", lanes)
        renames = dict(self.db.get_config("branch_renames") or {})
        renames[old] = new
        self.db.set_config("branch_renames", renames)
        self._sync_index_from_git()
        self.bus.publish({"type": "branch_renamed", "from": old, "to": new})
        self.bus.publish({"type": "git_changed", "what": "branch_renamed"})
        return {"name": new, "tip": self.git.branch_tip(new)}

    def merge_branch(self, name: str) -> dict[str, Any]:
        """Merge a branch into the current branch — a real merge commit."""
        into = self.git.current_branch()
        if not into:
            raise GitError("HEAD is detached at a mid-branch commit — set current to a branch tip first")
        if name == into:
            raise GitError(f"'{name}' is already the current branch")
        if not self.git.branch_tip(name):
            raise GitError(f"branch '{name}' does not exist")
        before = self.current_id
        sha = self.git.merge(name, into)
        if sha == before:
            raise GitError(f"'{name}' is already fully merged into {into} — nothing to merge")
        # Insert with a millisecond timestamp before the resync: git only keeps
        # seconds, which would make a merge look older than its own parents.
        self.db.insert_node({
            "id": sha,
            "parent_id": before,
            "created_at": _now_ms(),
            "run_id": None,
            "branch": into,
            "lane": self._branch_lanes().get(into, 0),
            "parents": [before, self.git.branch_tip(name)],
            "title": f"merge: branch {name} into {into}",
        })
        self._sync_index_from_git()
        self.db.set_config("current_id", sha)
        self.bus.publish({"type": "branch_merged", "branch": name, "into": into, "version": sha})
        self.bus.publish({"type": "current_changed", "currentId": sha})
        self.bus.publish({"type": "git_changed", "what": "merge"})
        return {"id": sha, "merged": name, "into": into}

    # ---------------------------------------------------------------- runs

    def start_run(
        self,
        trigger: str = "manual",
        set_current: bool = True,
        *,
        batch_size: int | None = None,
        executor_factory: ExecutorFactory | None = None,
    ) -> dict[str, Any]:
        """Freeze the oldest unanalyzed traces and optimize them. `batch_size`
        overrides the configured one, `executor_factory` replaces the Harbor
        executor for this run only."""
        if self.active_run():
            raise RuntimeError("one optimizer run at a time")
        batch_size = batch_size or self.db.get_config("batch_size")
        fresh = [t for t in self.db.traces() if t["status"] == "new"]
        batch = list(reversed(fresh))[:batch_size]  # oldest first
        if not batch:
            raise RuntimeError("no unanalyzed traces to optimize")
        run_id = ids.new_run_id()
        started = _now_ms()
        trace_ids = [t["session_id"] for t in batch]
        self.db.insert_run(
            {
                "id": run_id,
                "status": "running",
                "trigger": trigger,
                "started_at": started,
                "model": self.s.pipeline_label,
                "attempts": 1,
                "trace_ids": trace_ids,
                "base_version_id": self.current_id,
                "result_version_id": None,
            }
        )
        # Freeze the batch: these traces belong to this run from now on.
        for sid in trace_ids:
            self.db.execute("UPDATE traces SET analyzed_by = ? WHERE session_id = ?", (run_id, sid))
        self.emit(run_id, "log", "start", "MAJICS optimization started",
                  f"{self.s.pipeline_label} · batch of {len(trace_ids)} traces · {trigger}")
        # The roster up front, so the pipeline graph renders every seat as
        # pending from the first second (the in-sandbox driver re-posts it
        # with the same keys when it takes over).
        self.emit(run_id, "pipeline", None, "", extra={"attempt": 1,
                   "agents": _roster_payload(self.s)})
        self.emit(run_id, "log", "read", "Batch frozen",
                  ", ".join(trace_ids))
        self.bus.publish({"type": "run_started", "run": {"id": run_id, "status": "running"}})
        self._live[run_id] = {
            "working": self.git.file_at(self.current_id).splitlines(),
            "changes": [],
            "commit": None,
        }
        self._run_task = asyncio.get_running_loop().create_task(
            self._drive_run(run_id, trigger, set_current, executor_factory)
        )
        return {"id": run_id, "status": "running"}

    def _maybe_auto_optimize(self) -> None:
        try:
            if not self.db.get_config("auto_optimize"):
                return
            if self.active_run():
                return
            batch_size: int = self.db.get_config("batch_size")
            fresh = [t for t in self.db.traces() if t["status"] == "new"]
            if len(fresh) >= batch_size:
                self.start_run(trigger="auto")
        except RuntimeError:
            pass

    def _rel_at(self, run_id: str) -> int:
        run = self.db.run(run_id)
        if not run:
            return 0
        return max(0, _now_ms() - run["started_at"])

    def emit(
        self,
        run_id: str,
        kind: str,
        icon: str | None,
        text: str,
        detail: str | None = None,
        level: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        ev: dict[str, Any] = {"at": self._rel_at(run_id), "kind": kind}
        if icon:
            ev["icon"] = icon
        if text:
            ev["text"] = text
        if detail:
            ev["detail"] = detail
        if level:
            ev["level"] = level
        if extra:
            ev.update(extra)
        append_event(self.dirs.events_path(run_id), ev)
        self.bus.publish({"type": "run_event", "runId": run_id, "event": ev})

    def emit_status(self, run_id: str, status: str) -> None:
        ev = {"at": self._rel_at(run_id), "kind": "status", "status": status}
        append_event(self.dirs.events_path(run_id), ev)
        self.bus.publish({"type": "run_event", "runId": run_id, "event": ev})
        self.db.update_run(run_id, status=status)
        self.bus.publish({"type": "run_status", "runId": run_id, "status": status})

    async def record_pipeline_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Events POSTed live by MAJICS sessions inside the sandbox.

        The custom `edit` tool posts kind="change" (with edits + rationale +
        evidence), `feedback` posts kind="feedback", `git_commit` posts
        kind="commit" (title + body), and the agent hooks stream kind="tool" /
        "tool_result" / "agent". Change and commit events also update a live
        result so the dashboard shows edits as they happen.
        """
        run = self.db.run(run_id)
        if not run or run["status"] not in ("running", "validating"):
            return
        kind = event.get("kind", "log")
        ev: dict[str, Any] = {"at": self._rel_at(run_id), "kind": kind}
        for k, v in event.items():
            if k == "kind" or v is None:
                continue
            ev[k] = v
        append_event(self.dirs.events_path(run_id), ev)
        self.bus.publish({"type": "run_event", "runId": run_id, "event": ev})
        if kind == "change":
            self._apply_live_change(run_id, ev)
        elif kind == "commit":
            self._record_live_commit(run_id, ev)

    # ------------------------------------------------------- live run preview

    def _persist_live_result(self, run_id: str, live: dict[str, Any]) -> None:
        self.dirs.write_result(run_id, {
            "live": True,
            "signal": (live.get("commit") or {}).get("title", ""),
            "commit": live.get("commit") or {"title": "", "body": ""},
            "changes": [c.as_dict() for c in live.get("changes", [])],
        })

    def _apply_live_change(self, run_id: str, ev: dict[str, Any]) -> None:
        live = self._live.get(run_id)
        edits = ev.get("edits") or []
        if live is None or not edits:
            return
        working = "\n".join(live["working"])
        for e in edits:
            old = e.get("oldText") or ""
            new = e.get("newText") or ""
            if old and old in working:
                working = working.replace(old, new, 1)
        lines = working.splitlines()
        live["working"] = lines
        first = edits[0]
        old_text = first.get("oldText") or ""
        new_text = first.get("newText") or ""
        op = "insert" if (old_text == "" and new_text) else ("delete" if new_text == "" else "update")
        needle = new_text or old_text
        line = 0
        for idx, ln in enumerate(lines):
            if needle and needle in ln:
                line = idx + 1
                break
        section = patch._section_at(lines, line - 1) if line else "top level"
        live["changes"].append(patch.Change(
            op, section, line,
            before=old_text or None,
            after=new_text or None,
            rationale=ev.get("rationale") or "",
            evidence=ev.get("evidence") or [],
            anchor=old_text or None,
        ))
        self._persist_live_result(run_id, live)

    def _record_live_commit(self, run_id: str, ev: dict[str, Any]) -> None:
        live = self._live.get(run_id)
        if live is None:
            return
        live["commit"] = {
            "title": (ev.get("title") or "").strip(),
            "body": (ev.get("body") or "").strip(),
        }
        self._persist_live_result(run_id, live)

    def emit_change_events(self, run_id: str, changes: list[patch.Change]) -> None:
        """Draft + change events per verified edit, exactly once per run."""
        marker = self.dirs.run_dir(run_id) / ".edits-emitted"
        if marker.exists() or not changes:
            return
        for i, c in enumerate(changes):
            self.emit(
                run_id, "log", "draft", f"Proposing edit {i + 1} of {len(changes)}",
                f"{c.op} · {c.section}",
            )
            self.emit(run_id, "change", None, "", extra={"index": i})
        marker.write_text("1", encoding="utf-8")

    def record_run_outcome(
        self,
        run_id: str,
        outcome: str,
        note: str,
        title: str = "",
        body: str = "",
        signal: str = "",
        review: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Close a no-change or failed run out in the experience log."""
        run = self.db.run(run_id)
        if not run:
            return None
        entry = logedits.append_entry(
            self.dirs.log_edits,
            logedits.outcome_entry(
                run, outcome, note, title=title, body=body, signal=signal, review=review
            ),
        )
        self.emit(run_id, "log", "note", "Experience log updated",
                  f"log_edits.json {entry['id']} · {outcome}")
        self.bus.publish({"type": "log_edits_changed", "runId": run_id, "entryId": entry["id"]})
        return entry

    # ------------------------------------------------------------- the loop

    async def _drive_run(
        self, run_id: str, trigger: str, set_current: bool, executor_factory: ExecutorFactory | None
    ) -> None:
        from .majics import MajicsPipeline, PipelineFailure  # heavy deps, only when optimizing

        run = self.db.run(run_id)
        assert run is not None
        attempts_limit = self.s.optimization.max_attempts
        rejection: str | None = None
        success: dict[str, Any] | None = None
        pipeline = MajicsPipeline(self.s, self.dirs, run, self, executor_factory)
        try:
            for attempt in range(1, attempts_limit + 1):
                if attempt > 1:
                    self.db.update_run(run_id, attempts=attempt)
                    self.emit(run_id, "log", "retry", f"Retrying (attempt {attempt} of {attempts_limit})",
                              "verifier feedback appended; the review report is reused")
                try:
                    outcome = await pipeline.run(attempt, rejection)
                except PipelineFailure as exc:
                    rejection = str(exc)
                    self.emit(
                        run_id,
                        "log",
                        "fail",
                        f"Attempt {attempt} stage failed",
                        rejection,
                        "warn" if attempt < attempts_limit else "error",
                    )
                    continue
                if outcome["ok"]:
                    success = outcome
                    break
                rejection = outcome["reason"]
                self.emit(run_id, "log", "fail", f"Attempt {attempt} rejected", rejection, "warn")
        except Exception as exc:  # noqa: BLE001 — the run record must survive any failure
            rejection = f"pipeline infrastructure error: {exc}"
            self.emit(run_id, "log", "fail", "Pipeline error", str(exc), "error")

        ended = _now_ms()
        run = self.db.run(run_id)
        duration = ended - run["started_at"]
        trace_ids = run["trace_ids"]
        if success and success["changes"]:
            # Reveal the verified change cards now — the proposal landed.
            self.emit_change_events(run_id, success["changes"])
            node_id, branch, title = self._commit_run_result(run_id, run, success, set_current)
            self.emit_status(run_id, "succeeded")
            self.emit(run_id, "log", "check", f"Version {node_id} committed on {branch}",
                      f"{len(success['changes'])} edit{'s' if len(success['changes']) != 1 else ''} applied · {title}")
            self.db.update_run(
                run_id,
                status="succeeded",
                ended_at=ended,
                duration_ms=duration,
                result_version_id=node_id,
            )
        elif success is not None:
            # A valid run that found nothing to change: analyzed, but no commit.
            note = success["result"].get("signal") or "MAJICS returned an empty edit list."
            self.dirs.write_result(run_id, {"changes": [], "note": note})
            self.record_run_outcome(
                run_id, "no-changes", note,
                title=(success["result"].get("commit") or {}).get("title", ""),
                body=(success["result"].get("commit") or {}).get("body", ""),
                signal=success["result"].get("signal", ""),
                review=success["result"].get("review"),
            )
            self.emit(run_id, "log", "check", "Returned 0 edits",
                      "batch marked analyzed · no commit created")
            self.emit_status(run_id, "no-changes")
            self.db.update_run(
                run_id,
                status="no-changes",
                ended_at=ended,
                duration_ms=duration,
                note=f"MAJICS found no recurring signal in this batch. {note}. "
                     "Returning zero edits is a valid outcome, not an error.",
            )
        else:
            self.emit(run_id, "log", "fail", "Run failed — nothing applied",
                      f"AGENTS.md stays at {run['base_version_id']}", "error")
            self.record_run_outcome(
                run_id,
                "failed",
                rejection or "unknown rejection",
                review=pipeline.review_memory(),
            )
            self.emit_status(run_id, "failed")
            self.db.update_run(
                run_id,
                status="failed",
                ended_at=ended,
                duration_ms=duration,
                note=f"All {run['attempts']} attempts rejected by the verifier — {rejection}. "
                     f"AGENTS.md was left at {run['base_version_id']}.",
            )
        self.db.mark_traces_analyzed(trace_ids, run_id)
        self.bus.publish({"type": "run_completed", "runId": run_id})
        self._live.pop(run_id, None)
        self._run_task = None

    def _commit_run_result(
        self, run_id: str, run: dict[str, Any], success: dict[str, Any], set_current: bool
    ) -> tuple[str, str, str]:
        """Apply a verified run as a Git commit with the judge's message."""
        result = success["result"]
        changes = success["changes"]
        title, body = patch.verify_commit_message(result)
        base_id = run["base_version_id"]
        new_file = "\n".join(success["new_file"]) + "\n"
        branch, lane = self._branch_for_child(base_id)
        prev_branch = self.git.current_branch()
        prev_head = self.current_id

        if self.git.branch_tip(branch) == base_id:
            self.git.checkout(branch)
        else:  # fork: a child of a non-tip version opens a new lane
            self.git.create_branch(branch, base_id)
            self.git.checkout(branch)
        sha = self.git.commit_worktree(
            new_file,
            title,
            body,
            trailers={
                "Hone-Run": run_id,
                "Hone-Signal": result.get("signal", ""),
                "Hone-Branch": branch,
            },
            author=OPTIMIZER_AUTHOR,
        )
        self.db.insert_node({
            "id": sha,
            "parent_id": base_id,
            "created_at": _now_ms(),
            "run_id": run_id,
            "branch": branch,
            "lane": lane,
            "parents": [base_id],
            "title": title,
        })
        self.dirs.write_result(run_id, {
            **result,
            "changes": [c.as_dict() for c in changes],
            "nodeId": sha,
            "baseVersionId": base_id,
            "commitTitle": title,
            "commitBody": body,
            "commitBranch": branch,
        })
        entry = logedits.append_entry(
            self.dirs.log_edits,
            logedits.applied_entry(
                run, sha, branch, title, body, result, changes,
                self.git.file_at(base_id).splitlines(), success["new_file"],
            ),
        )
        self.emit(run_id, "log", "note", "Experience log updated",
                  f"log_edits.json {entry['id']} · applied · {len(changes)} change(s)")
        self.bus.publish({"type": "log_edits_changed", "runId": run_id, "entryId": entry["id"]})
        if set_current:
            self.db.set_config("current_id", sha)
            self.bus.publish({"type": "current_changed", "currentId": sha})
        elif prev_head != sha:
            # The commit is the run's result, not the served version: put HEAD back.
            if prev_branch:
                self.git.checkout(prev_branch)
            else:
                self.git.checkout(prev_head)
        self.bus.publish({"type": "git_changed", "what": "commit"})
        return sha, branch, title

    def _branch_for_child(self, base_id: str) -> tuple[str, int]:
        """A child of a branch tip continues that branch; any other base forks.
        The branch HEAD currently serves wins when the base is its tip."""
        base = self.db.node(base_id)
        assert base is not None
        current = self.git.current_branch()
        if current and self.git.branch_tip(current) == base_id:
            return current, self._branch_lanes().get(current, base["lane"])
        base_branch = base["branch"]
        if self.git.branch_tip(base_branch) == base_id:
            return base_branch, base["lane"]
        existing = {b["name"] for b in self.git.branches()}
        for k in range(2, 64):
            name = f"{AUTO_BRANCH_PREFIX}{k}"
            if name not in existing:
                lanes = self._branch_lanes()
                lane = lanes.setdefault(name, (max(lanes.values()) + 1) if lanes else 0)
                self.db.set_config("branch_lanes", lanes)
                return name, lane
        return TRUNK, 0

    def events_of(self, run_id: str) -> list[dict[str, Any]]:
        return read_events(self.dirs.events_path(run_id))


def _iter_messages(body: str):
    """Yield (role, content) for both raw message lines and pi's wrapped form."""
    for raw in body.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "session":
            yield "session", entry
            continue
        msg = entry.get("message") if entry.get("type") == "message" else entry
        if isinstance(msg, dict) and msg.get("role"):
            yield msg["role"], msg.get("content")


def _summarize_jsonl(body: bytes) -> tuple[str, int, str | None]:
    """Extract first user line, turn count, and the AGENTS.md version header if present."""
    first_line = ""
    turns = 0
    version = None
    for role, payload in _iter_messages(body.decode("utf-8", errors="replace")):
        if role == "session":
            version = payload.get("agents_md") or version
            continue
        if role not in ("user", "assistant"):
            continue
        turns += 1
        if role == "user":
            content = payload
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
                )
            if not first_line and text.strip():
                first_line = text.strip().splitlines()[0][:120]
    return first_line, turns, version
