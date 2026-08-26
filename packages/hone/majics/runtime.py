"""Single source of truth for the MAJICS sandbox runtime contract."""

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
