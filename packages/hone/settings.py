"""Load the single HoneConfig runtime object from hone.yaml."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config import HoneConfig, load_dotenv, load_yaml_config

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Environment variables remain a deployment override surface. They are
# applied to the raw YAML before its one and only Pydantic validation pass.
_ENV_PATHS: dict[str, tuple[str, str]] = {
    "HONE_DATA_DIR": ("service", "data_dir"),
    "HONE_TOKEN": ("service", "token"),
    "HONE_HOST": ("service", "host"),
    "HONE_PORT": ("service", "port"),
    "HONE_ANNOUNCE_HOST": ("service", "announce_host"),
    "HONE_UI_DIR": ("service", "ui_dir"),
    "HONE_EXPOSE_WRITE_TOKEN": ("service", "expose_write_token"),
    "HONE_DEMO": ("service", "demo"),
    "HONE_DEMO_DATE": ("service", "demo_date"),
    "MODEL_NAME": ("target", "model"),
    "HONE_MAX_ATTEMPTS": ("optimization", "max_attempts"),
    "HONE_MAJICS_TIMEOUT": ("optimization", "stage_timeout_s"),
}


def _root_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_REPO_ROOT / path).resolve()


def load_settings(
    *,
    config_path: str | Path | None = None,
    dotenv_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> HoneConfig:
    """Load, overlay, validate, and return the sole runtime configuration."""
    supplied = dict(environ or {})
    dotenv = _root_path(
        dotenv_path or supplied.get("HONE_DOTENV") or os.environ.get("HONE_DOTENV", ".env")
    )
    load_dotenv(dotenv)
    effective = {**os.environ, **supplied}

    config_file = _root_path(
        config_path or effective.get("HONE_CONFIG", "hone.yaml")
    )
    raw: dict[str, Any] = load_yaml_config(config_file, environment=effective)
    for env_name, (section, key) in _ENV_PATHS.items():
        if env_name in effective:
            raw.setdefault(section, {})[key] = effective[env_name]

    config = HoneConfig.model_validate(raw)
    service = config.service

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else (config_file.parent / path).resolve()

    return config.model_copy(update={
        "service": service.model_copy(update={
            "data_dir": resolved(service.data_dir),
            "ui_dir": resolved(service.ui_dir),
        }),
        "majics": config.majics.with_credentials(effective),
    })
