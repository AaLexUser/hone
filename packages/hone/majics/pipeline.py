"""The two-stage MAJICS optimization pipeline as Harbor jobs.

One optimization run drives TWO Harbor tasks. A custom Harbor agent launches
the MAJICS driver directly inside each task environment:

- **review job** — the driver fans the reviewer prompt out to every configured pi
  sessions on different models (all-or-nothing), then the review judge
  cross-examines them and submits `review.json`; the host renders report.html.
- **propose job** — every configured proposer reads the judged review + experience
  history and submit proposals; the propose judge cross-examines them and
  submits the fused `proposal.json` (edits + commit message).

A verifier rejection re-runs only the propose job with the rejection text;
the review report is reused. The service then re-verifies the edits and
commits them to the AGENTS.md git repository.

The in-sandbox workflow originated in ``reference/rejudge`` (see
``driver/majics.ts``). This module coordinates task construction, Harbor
execution, artifact collection, and host-side verification.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .. import patch
from ..config import HoneConfig
from ..store import DataDirs
from .executor import HarborMajicsExecutor
from .report import ReviewError, render_review, validate_review
from .runtime import collect_artifacts
from .task import MajicsTaskBuilder


class PipelineFailure(RuntimeError):
    """The pipeline failed; the message feeds the next attempt or the note."""


class StageExecutor(Protocol):
    """Runs one materialized MAJICS task and returns its Harbor job dir."""

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path: ...


ExecutorFactory = Callable[[HoneConfig, DataDirs, str, Callable[..., Any]], StageExecutor]


class MajicsPipeline:
    """Host-side driver of the two Harbor jobs; the report is cached across
    propose retries."""

    def __init__(self, settings: HoneConfig, dirs: DataDirs, run: dict[str, Any], hone,
                 executor_factory: ExecutorFactory | None = None) -> None:
        self.s = settings
        self.dirs = dirs
        self.run_row = run
        self.hone = hone
        self.run_id = run["id"]
        self.report_html: str | None = None
        self.review: dict[str, Any] | None = None
        self.review_json: str | None = None
        self.task_builder = MajicsTaskBuilder(settings, dirs, run, hone)
        self.executor = (executor_factory or HarborMajicsExecutor)(settings, dirs, self.run_id, self._emit)

    # ------------------------------------------------------------- plumbing

    def _emit(self, kind: str, **extra: Any) -> None:
        ev = {"kind": kind, **{k: v for k, v in extra.items() if v is not None}}
        self.hone.emit(self.run_id, kind, None, "", extra=ev)

    def _stage_failure(self, stage: str, attempt: int, artifacts: dict[str, str]) -> PipelineFailure:
        err = artifacts.get("driver-error.txt", "").strip()
        if err:
            return PipelineFailure(f"{stage} stage failed: {err.splitlines()[0][:400]}")
        return PipelineFailure(
            f"{stage} stage produced no result — see majics/{stage}-a{attempt}/"
            f"jobs/{self.run_id}-{stage}-a{attempt}/job.log in the run dir")

    def review_memory(self) -> dict[str, Any] | None:
        if self.review is None:
            return None
        return {
            "runId": self.run_id,
            "summary": self.review["summary"],
            "hypotheses": [
                {
                    "statement": item["statement"],
                    "traceIds": item["traceIds"],
                    "confidence": item["confidence"],
                }
                for item in self.review["hypotheses"][:5]
            ],
        }

    # --------------------------------------------------------------- drive

    async def run(self, attempt: int, rejection: str | None) -> dict[str, Any]:
        """One attempt: the review job runs once per run (its report is
        cached); every attempt runs the propose job. The outcome shape is
        what the service already knows how to commit."""
        if self.review_json is None:
            task = self.task_builder.materialize("review", attempt, None, None)
            job_dir = await self.executor.run("review", task, attempt)
            artifacts = collect_artifacts(job_dir)
            review_text = artifacts.get("review.json")
            if not review_text:
                raise self._stage_failure("review", attempt, artifacts)
            try:
                review = validate_review(json.loads(review_text), self.run_row["trace_ids"])
            except (json.JSONDecodeError, ReviewError) as exc:
                raise PipelineFailure(f"review stage produced invalid review.json: {exc}") from exc
            self.review = review
            self.review_json = json.dumps(review, ensure_ascii=False, indent=2) + "\n"
            self.dirs.review_path(self.run_id).write_text(self.review_json, encoding="utf-8")
            self.report_html = render_review(review)
            self.dirs.report_path(self.run_id).write_text(self.report_html, encoding="utf-8")

        task = self.task_builder.materialize(
            "propose", attempt, rejection, self.review_json
        )
        job_dir = await self.executor.run("propose", task, attempt)
        artifacts = collect_artifacts(job_dir)
        proposal_text = artifacts.get("proposal.json")
        if not proposal_text:
            raise self._stage_failure("propose", attempt, artifacts)
        try:
            proposal = json.loads(proposal_text)
        except json.JSONDecodeError as exc:
            raise PipelineFailure(f"propose stage produced invalid JSON: {exc}") from exc
        if not isinstance(proposal, dict):
            raise PipelineFailure("propose stage result must be a JSON object")
        return self._verdict(proposal)

    def _verdict(self, proposal: dict[str, Any]) -> dict[str, Any]:
        base_file = self.hone.git.file_at(self.run_row["base_version_id"]).splitlines()
        edits = proposal.get("edits")
        if not isinstance(edits, list):
            return {"ok": False, "reason": "proposal.edits must be a JSON array"}
        raw_title = proposal.get("commit_title")
        raw_body = proposal.get("commit_body")
        raw_note = proposal.get("note")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        body = raw_body.strip() if isinstance(raw_body, str) else ""
        signal = raw_note.strip() if isinstance(raw_note, str) else ""
        result = {
            "signal": signal or title or "no signal",
            "commit": {"title": title, "body": body},
            "review": self.review_memory(),
        }

        if not edits:
            return {"ok": True, "changes": [], "new_file": base_file, "result": result}

        try:
            patch.verify_commit_message(result)
            changes, new_file = patch.apply_proposal_edits(
                edits, base_file, self.run_row["trace_ids"]
            )
        except patch.PatchError as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": True, "changes": changes, "new_file": new_file, "result": result}
