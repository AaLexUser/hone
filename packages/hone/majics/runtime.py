"""Single source of truth for the MAJICS sandbox runtime contract."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

CONTAINER_APP_DIR = "/app"
CONTAINER_DRIVER_DIR = "/app-driver"
CONTAINER_DRIVER_PATH = f"{CONTAINER_DRIVER_DIR}/majics.ts"
SERVICE_TOKEN_ENV = "HONE_MAJICS_SERVICE_TOKEN"
AGENT_IMPORT_PATH = "hone.majics.agent:MajicsAgent"
BUILD_ALLOWED_HOSTS = (
    "github.com",
    "codeload.github.com",
    "registry.npmjs.org",
    "raw.githubusercontent.com",
    "nodejs.org",
)


def driver_command() -> str:
    return f"node --experimental-strip-types {CONTAINER_DRIVER_PATH}"


def emit_launch(emit: Callable[..., Any], stage: str) -> None:
    """The log line every stage executor writes as its Harbor job starts."""
    emit("log", icon="read", text=f"{stage} job: launching Harbor", detail=f"custom agent · {AGENT_IMPORT_PATH}")


def collect_artifacts(job_dir: Path) -> dict[str, str]:
    """The flat artifacts a stage's task collected out of the sandbox."""
    artifacts_dir = next((c for c in sorted(job_dir.glob("task__*/artifacts")) if c.is_dir()), None)
    if artifacts_dir is None:
        return {}
    return {f.name: f.read_text(encoding="utf-8", errors="replace") for f in artifacts_dir.iterdir() if f.is_file()}
