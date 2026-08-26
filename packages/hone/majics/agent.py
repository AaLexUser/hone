"""Harbor agent adapter that launches the materialized MAJICS graph directly."""

from __future__ import annotations

from typing import override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .runtime import CONTAINER_APP_DIR, CONTAINER_DRIVER_PATH, driver_command


class MajicsAgent(BaseAgent):
    """A deterministic Harbor agent whose runtime is the MAJICS driver itself."""

    @staticmethod
    @override
    def name() -> str:
        return "majics"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        # The task image contains Node, the Pi SDK, models.json, and the driver.
        # Keeping setup empty also lets Harbor cache the fully built image.
        return None

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del instruction
        result = await environment.exec(
            command=driver_command(),
            cwd=CONTAINER_APP_DIR,
            env={**self.extra_env, "NODE_NO_WARNINGS": "1"},
        )
        context.metadata = {
            "pipeline": "majics",
            "entrypoint": CONTAINER_DRIVER_PATH,
            "return_code": result.return_code,
        }
        if result.return_code != 0:
            output = (result.stderr or result.stdout or "no driver output").strip()
            raise RuntimeError(
                f"MAJICS driver exited with {result.return_code}: {output[-2000:]}"
            )
