"""Materialize one MAJICS stage as a Harbor task bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .. import logedits
from ..config import HoneConfig
from ..store import DataDirs
from ..trace_evidence import compile_run
from . import assets
from .runtime import (
    BUILD_ALLOWED_HOSTS,
    CONTAINER_APP_DIR,
    CONTAINER_DRIVER_DIR,
    CONTAINER_DRIVER_PATH,
)

_NVM_VERSION = "v0.40.2"


def _merge_feedback(body: str, feedback: str) -> str:
    out = []
    for line in body.splitlines():
        if line.strip() and not out:
            try:
                header = json.loads(line)
                if header.get("type") == "session":
                    header["feedback"] = feedback
                    line = json.dumps(header, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        out.append(line)
    return "\n".join(out) + "\n"


class MajicsTaskBuilder:
    """Build the immutable files consumed by one sandboxed stage."""

    def __init__(
        self,
        settings: HoneConfig,
        dirs: DataDirs,
        run: dict[str, Any],
        hone: Any,
    ) -> None:
        self.s = settings
        self.dirs = dirs
        self.run = run
        self.hone = hone

    def _roster(self) -> dict[str, Any]:
        config = self.s.majics
        return {
            "reviewModels": [config.seat_spec(seat) for seat in config.review.panel],
            "reviewJudge": config.seat_spec(config.review.judge),
            "proposeModels": [config.seat_spec(seat) for seat in config.propose.panel],
            "proposeJudge": config.seat_spec(config.propose.judge),
        }

    def _workspace(self, environment: Path) -> None:
        workspace = environment / "workspace"
        traces = workspace / "traces"
        traces.mkdir(parents=True)
        for session_id in self.run["trace_ids"]:
            source = self.dirs.trace_path(session_id)
            body = source.read_text(encoding="utf-8") if source.exists() else ""
            if not body:
                continue
            row = self.hone.db.one(
                "SELECT feedback FROM traces WHERE session_id = ?", (session_id,)
            )
            feedback = (row or {}).get("feedback")
            if feedback:
                body = _merge_feedback(body, feedback)
            (traces / f"{session_id}.jsonl").write_text(body, encoding="utf-8")
        (workspace / "agents.md").write_text(
            self.hone.git.file_at(self.run["base_version_id"]), encoding="utf-8"
        )
        (workspace / "batch.json").write_text(
            json.dumps(self.run["trace_ids"], indent=2), encoding="utf-8"
        )
        evidence = self.dirs.evidence_path(self.run["id"])
        if not evidence.exists():
            self.dirs.write_evidence(
                self.run["id"],
                compile_run(self.dirs, self.hone.db, self.run),
            )
        shutil.copyfile(evidence, workspace / "evidence.json")
        (workspace / "log_edits.json").write_text(
            json.dumps(
                logedits.sandbox_copy(self.hone.log_edits_payload()),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def _allowlist_toml(self) -> str:
        entries = list(dict.fromkeys([
            *self.s.majics.provider_hosts(),
            self.s.service.announce_host,
            *BUILD_ALLOWED_HOSTS,
        ]))
        return ", ".join(f'"{host}"' for host in entries)

    def materialize(
        self,
        stage: str,
        attempt: int,
        rejection: str | None,
        review_json: str | None,
    ) -> Path:
        base = self.dirs.run_dir(self.run["id"]) / "majics" / f"{stage}-a{attempt}"
        if base.exists():
            shutil.rmtree(base)
        task = base / "task"
        environment = task / "environment"
        (task / "tests").mkdir(parents=True)
        self._workspace(environment)
        if stage == "propose" and review_json is not None:
            (environment / "workspace" / "review.json").write_text(
                review_json, encoding="utf-8"
            )

        config_dir = environment / "config"
        (config_dir / "prompts").mkdir(parents=True)
        (config_dir / "majics.json").write_text(json.dumps({
            "mode": stage,
            "attempt": attempt,
            "rejection": rejection,
            "followUpTimeoutS": self.s.optimization.follow_up_timeout_s,
            "turnTimeoutS": self.s.optimization.turn_timeout_s,
            **self._roster(),
        }, indent=2), encoding="utf-8")
        (config_dir / "hone.json").write_text(json.dumps({
            "url": f"http://{self.s.service.announce_host}:{self.s.service.port}",
            "runId": self.run["id"],
        }), encoding="utf-8")
        for name, text in assets.PROMPT_FILES.items():
            (config_dir / "prompts" / name).write_text(text, encoding="utf-8")

        pi_home = environment / "pi-home"
        pi_home.mkdir(parents=True)
        (pi_home / "models.json").write_text(
            self.s.majics.models_json(), encoding="utf-8"
        )
        shutil.copyfile(Path(__file__).parent / "driver" / "majics.ts", environment / "majics.ts")
        (environment / "package.json").write_text(assets.PACKAGE_JSON, encoding="utf-8")

        artifacts = ["review.json"] if stage == "review" else ["proposal.json"]
        artifacts.append("driver-error.txt")
        artifact_lines = ",\n".join(
            f'{{ source = "{CONTAINER_APP_DIR}/{name}", destination = "{name}" }}'
            for name in artifacts
        )
        (environment / "Dockerfile").write_text(
            assets.DOCKERFILE_TEMPLATE.format(
                nvm_version=_NVM_VERSION,
                app_dir=CONTAINER_APP_DIR,
                driver_dir=CONTAINER_DRIVER_DIR,
                driver_path=CONTAINER_DRIVER_PATH,
            ),
            encoding="utf-8",
        )
        (task / "task.toml").write_text(
            assets.TASK_TOML_TEMPLATE.format(
                stage=stage,
                agent_timeout=float(self.s.optimization.stage_timeout_s),
                allowlist=self._allowlist_toml(),
                artifacts=artifact_lines,
            ),
            encoding="utf-8",
        )
        (task / "instruction.md").write_text(assets.instruction(), encoding="utf-8")
        (task / "tests" / "test.sh").write_text(assets.TEST_SH, encoding="utf-8")
        (task / ".gitignore").write_text("agent/\n", encoding="utf-8")
        return task
