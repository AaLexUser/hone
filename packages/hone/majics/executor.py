"""Harbor-specific execution boundary for materialized MAJICS tasks."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any

from harbor.job import Job
from harbor.models.job.config import JobConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig

from ..config import HoneConfig
from ..store import DataDirs
from .runtime import AGENT_IMPORT_PATH, BUILD_ALLOWED_HOSTS, SERVICE_TOKEN_ENV, emit_launch


@contextmanager
def _runtime_environment(values: dict[str, str]):
    """Expose secrets while Harbor resolves templates, then restore the host."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class HarborMajicsExecutor:
    def __init__(
        self,
        settings: HoneConfig,
        dirs: DataDirs,
        run_id: str,
        emit: Callable[..., Any],
    ) -> None:
        self.s = settings
        self.dirs = dirs
        self.run_id = run_id
        self.emit = emit

    def job_config(self, stage: str, task_dir: Path, attempt: int) -> JobConfig:
        jobs_dir = self.dirs.run_dir(self.run_id) / "majics" / f"{stage}-a{attempt}" / "jobs"
        agent_hosts = list(dict.fromkeys([
            self.s.service.announce_host,
            *self.s.majics.provider_hosts(),
        ]))
        return JobConfig(
            job_name=f"{self.run_id}-{stage}-a{attempt}",
            jobs_dir=jobs_dir,
            n_attempts=1,
            n_concurrent_trials=1,
            quiet=True,
            agents=[AgentConfig(
                import_path=AGENT_IMPORT_PATH,
                extra_allowed_hosts=agent_hosts,
                env={
                    **self.s.majics.credential_templates(),
                    SERVICE_TOKEN_ENV: f"${{{SERVICE_TOKEN_ENV}}}",
                },
            )],
            environment=EnvironmentConfig(extra_allowed_hosts=list(BUILD_ALLOWED_HOSTS)),
            tasks=[TaskConfig(path=task_dir)],
        )

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path:
        config = self.job_config(stage, task_dir, attempt)
        emit_launch(self.emit, stage)
        runtime_env = {
            **self.s.majics.credential_env(),
            SERVICE_TOKEN_ENV: self.s.service.token,
        }
        with _runtime_environment(runtime_env):
            job = await Job.create(config)
            await job.run()
        return job.job_dir
