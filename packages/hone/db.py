"""SQLite: exactly four tables — traces, runs, nodes, config — in WAL mode."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  session_id  TEXT PRIMARY KEY,
  first_line  TEXT NOT NULL DEFAULT '',
  received_at INTEGER NOT NULL,
  turns       INTEGER NOT NULL DEFAULT 0,
  feedback    TEXT,
  status      TEXT NOT NULL DEFAULT 'new',
  version_id  TEXT NOT NULL,
  analyzed_by TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id               TEXT PRIMARY KEY,
  status           TEXT NOT NULL,
  trigger          TEXT NOT NULL,
  started_at       INTEGER NOT NULL,
  ended_at         INTEGER,
  duration_ms      INTEGER,
  model            TEXT NOT NULL,
  attempts         INTEGER NOT NULL DEFAULT 1,
  trace_ids        TEXT NOT NULL DEFAULT '[]',
  base_version_id  TEXT NOT NULL,
  result_version_id TEXT,
  note             TEXT
);
CREATE TABLE IF NOT EXISTS nodes (
  id         TEXT PRIMARY KEY,
  parent_id  TEXT,
  created_at INTEGER NOT NULL,
  run_id     TEXT,
  branch     TEXT NOT NULL,
  lane       INTEGER NOT NULL DEFAULT 0,
  parents    TEXT NOT NULL DEFAULT '[]',
  title      TEXT
);
CREATE TABLE IF NOT EXISTS config (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""


class Db:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- config helpers -------------------------------------------------

    def get_config(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM config WHERE key = ?", (key,))
        if row is None:
            return default
        return json.loads(row["value"])

    def set_config(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # ---- traces ----------------------------------------------------------

    def upsert_trace(self, t: dict[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO traces (session_id, first_line, received_at, turns, feedback, status, version_id, analyzed_by)
            VALUES (:session_id, :first_line, :received_at, :turns, :feedback, :status, :version_id, :analyzed_by)
            ON CONFLICT(session_id) DO UPDATE SET
              first_line = excluded.first_line,
              received_at = excluded.received_at,
              turns = excluded.turns,
              version_id = excluded.version_id
            """,
            {
                "session_id": t["session_id"],
                "first_line": t.get("first_line", ""),
                "received_at": t.get("received_at", int(time.time() * 1000)),
                "turns": t.get("turns", 0),
                "feedback": t.get("feedback"),
                "status": t.get("status", "new"),
                "version_id": t.get("version_id", ""),
                "analyzed_by": t.get("analyzed_by"),
            },
        )

    def set_trace_feedback(self, session_id: str, text: str) -> bool:
        # Feedback accumulates: a session can be rated turn by turn, and each
        # note is evidence the optimizer must see.
        cur = self.execute(
            "UPDATE traces SET feedback = CASE WHEN feedback IS NULL OR feedback = '' "
            "THEN ? ELSE feedback || char(10) || ? END WHERE session_id = ?",
            (text, text, session_id),
        )
        return cur.rowcount > 0

    def mark_traces_analyzed(self, session_ids: list[str], run_id: str) -> None:
        for sid in session_ids:
            self.execute(
                "UPDATE traces SET status = 'analyzed', analyzed_by = ? WHERE session_id = ?",
                (run_id, sid),
            )

    def traces(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM traces ORDER BY received_at DESC")

    # ---- runs ------------------------------------------------------------

    def insert_run(self, r: dict[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO runs (id, status, trigger, started_at, ended_at, duration_ms, model,
                              attempts, trace_ids, base_version_id, result_version_id, note)
            VALUES (:id, :status, :trigger, :started_at, :ended_at, :duration_ms, :model,
                    :attempts, :trace_ids, :base_version_id, :result_version_id, :note)
            """,
            {
                "id": r["id"],
                "status": r["status"],
                "trigger": r["trigger"],
                "started_at": r["started_at"],
                "ended_at": r.get("ended_at"),
                "duration_ms": r.get("duration_ms"),
                "model": r["model"],
                "attempts": r.get("attempts", 1),
                "trace_ids": json.dumps(r.get("trace_ids", [])),
                "base_version_id": r["base_version_id"],
                "result_version_id": r.get("result_version_id"),
                "note": r.get("note"),
            },
        )

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "trace_ids" in fields:
            fields["trace_ids"] = json.dumps(fields["trace_ids"])
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        params = dict(fields)
        params["id"] = run_id
        self.execute(f"UPDATE runs SET {cols} WHERE id = :id", params)

    def runs(self) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM runs ORDER BY started_at DESC")
        for r in rows:
            r["trace_ids"] = json.loads(r["trace_ids"])
        return rows

    def run(self, run_id: str) -> dict[str, Any] | None:
        r = self.one("SELECT * FROM runs WHERE id = ?", (run_id,))
        if r:
            r["trace_ids"] = json.loads(r["trace_ids"])
        return r

    # ---- nodes -----------------------------------------------------------

    def insert_node(self, n: dict[str, Any]) -> None:
        self.execute(
            "INSERT INTO nodes (id, parent_id, created_at, run_id, branch, lane, parents, title) "
            "VALUES (:id, :parent_id, :created_at, :run_id, :branch, :lane, :parents, :title)",
            {
                "parents": json.dumps(n.get("parents") or ([n["parent_id"]] if n.get("parent_id") else [])),
                "title": n.get("title"),
                **{k: n.get(k) for k in ("id", "parent_id", "created_at", "run_id", "branch", "lane")},
            },
        )

    def replace_all_nodes(self, rows: list[dict[str, Any]]) -> None:
        """Rebuild the index from Git history in one transaction."""
        with self._lock:
            self._conn.execute("DELETE FROM nodes")
            for n in rows:
                self._conn.execute(
                    "INSERT INTO nodes (id, parent_id, created_at, run_id, branch, lane, parents, title) "
                    "VALUES (:id, :parent_id, :created_at, :run_id, :branch, :lane, :parents, :title)",
                    {
                        "parents": json.dumps(n.get("parents") or []),
                        "title": n.get("title"),
                        **{k: n.get(k) for k in ("id", "parent_id", "created_at", "run_id", "branch", "lane")},
                    },
                )
            self._conn.commit()

    def _node_row(self, r: dict[str, Any]) -> dict[str, Any]:
        r["parents"] = json.loads(r.get("parents") or "[]")
        if not r["parents"] and r.get("parent_id"):
            r["parents"] = [r["parent_id"]]
        return r

    def nodes(self) -> list[dict[str, Any]]:
        return [self._node_row(r) for r in self.query("SELECT * FROM nodes ORDER BY created_at ASC")]

    def node(self, node_id: str) -> dict[str, Any] | None:
        r = self.one("SELECT * FROM nodes WHERE id = ?", (node_id,))
        return self._node_row(r) if r else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
