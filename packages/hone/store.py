"""Durable /data layout: traces/, repo/ (the Git history), runs/,
log_edits.json (the optimizer's experience history).

AGENTS.md is tracked by a real Git repository at /data/repo — versions are
commits, branches are branches, current is HEAD.
"""

from __future__ import annotations

from pathlib import Path

# The seed AGENTS.md is the first Pi workspace file: the loop starts from it.
SEED_AGENTS_MD = """\
# AGENTS.md
"""

SEED_COMMIT_TITLE = "feat: seed AGENTS.md for the workspace"
SEED_COMMIT_BODY = (
    "Initial instruction file every Pi session loads at start. "
    "Optimized versions of this file are committed on top by Hone MAJICS."
)


class DataDirs:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.traces = root / "traces"
        self.repo = root / "repo"
        self.current_file = self.repo / "AGENTS.md"
        self.runs = root / "runs"
        self.log_edits = root / "log_edits.json"
        for d in (self.traces, self.runs):
            d.mkdir(parents=True, exist_ok=True)

    # -- traces -------------------------------------------------------------

    def trace_path(self, session_id: str) -> Path:
        return self.traces / f"{session_id}.jsonl"

    def write_trace(self, session_id: str, body: bytes) -> Path:
        p = self.trace_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        return p

    # -- current file (the repo working tree at HEAD) ------------------------

    def write_current(self, text: str) -> None:
        self.current_file.write_text(text, encoding="utf-8")

    def read_current(self) -> str:
        return self.current_file.read_text(encoding="utf-8")

    # -- runs ---------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        d = self.runs / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def replay_path(self, run_id: str) -> Path:
        """Where a run replayed from the run cache notes its source."""
        return self.run_dir(run_id) / "replay.json"

    def result_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "result.json"

    def report_path(self, run_id: str) -> Path:
        """The review judge's HTML report for this run, when it produced one."""
        return self.run_dir(run_id) / "report.html"

    def review_path(self, run_id: str) -> Path:
        """The review judge's structured synthesis for this run."""
        return self.run_dir(run_id) / "review.json"

    def evidence_path(self, run_id: str) -> Path:
        """Shared deterministic research index for one frozen run."""
        return self.run_dir(run_id) / "evidence.json"

    def write_evidence(self, run_id: str, payload: dict) -> Path:
        import json

        path = self.evidence_path(run_id)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def write_result(self, run_id: str, payload: dict) -> Path:
        import json

        p = self.result_path(run_id)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p
