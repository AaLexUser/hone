"""Typed configuration for the Hone service and its MAJICS pipeline."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
PiThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ModelInput = Literal["text", "image"]

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def load_dotenv(path: str | Path = ".env") -> None:
    """Load a simple dotenv file without replacing exported environment values."""
    dotenv = Path(path)
    if not dotenv.exists():
        return
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _expand_env(value: Any, environment: Mapping[str, str] | None = None) -> Any:
    source = os.environ if environment is None else environment
    if isinstance(value, str):
        return _ENV_PATTERN.sub(
            lambda match: source.get(match.group(1), match.group(2) or ""),
            value,
        )
    if isinstance(value, list):
        return [_expand_env(item, source) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item, source) for key, item in value.items()}
    return value


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml_config(
    path: str | Path,
    _stack: tuple[Path, ...] = (),
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Load YAML, recursively merge ``extends``, then expand ``${ENV:-default}``."""
    config_path = Path(path).resolve()
    if config_path in _stack:
        chain = " -> ".join(str(item) for item in (*_stack, config_path))
        raise ValueError(f"Hone config has a circular extends chain: {chain}")
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"Hone config cannot be read at {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Hone config at {config_path} is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Hone config at {config_path} must contain a YAML mapping")

    raw = dict(parsed)
    extends = raw.pop("extends", None)
    if extends is None:
        return _expand_env(raw, environment)
    if isinstance(extends, str):
        parents = [extends]
    elif isinstance(extends, list) and all(isinstance(item, str) for item in extends):
        parents = extends
    else:
        raise ValueError(f'Hone config "extends" at {config_path} must be a path or list of paths')

    merged: dict[str, Any] = {}
    for parent in parents:
        expanded_parent = _expand_env(parent, environment)
        parent_path = (config_path.parent / expanded_parent).resolve()
        merged = _deep_merge(
            merged,
            load_yaml_config(parent_path, (*_stack, config_path), environment),
        )
    return _expand_env(_deep_merge(merged, raw), environment)


class FrozenConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelCostTier(FrozenConfigModel):
    input_tokens_above: int = Field(ge=0)
    input: float = Field(default=0, ge=0)
    output: float = Field(default=0, ge=0)
    cache_read: float = Field(default=0, ge=0)
    cache_write: float = Field(default=0, ge=0)

    def to_pi(self) -> dict[str, int | float]:
        return {
            "inputTokensAbove": self.input_tokens_above,
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
        }


class ModelCost(FrozenConfigModel):
    input: float = Field(default=0, ge=0)
    output: float = Field(default=0, ge=0)
    cache_read: float = Field(default=0, ge=0)
    cache_write: float = Field(default=0, ge=0)
    tiers: list[ModelCostTier] = Field(default_factory=list)

    def to_pi(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
        }
        if self.tiers:
            payload["tiers"] = [tier.to_pi() for tier in self.tiers]
        return payload


class ProviderConfig(FrozenConfigModel):
    """One Pi custom provider shared by any number of configured models."""

    base_url: str
    api: str = "openai-completions"
    # Pi resolves this as an environment-variable name at request time. Hone
    # never serializes the corresponding credential into a task or image.
    api_key_env: str | None = None
    name: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    auth_header: bool | None = None
    compat: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_url", "api")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", value):
            raise ValueError("must name an environment variable, not contain a literal secret")
        return value

    @field_validator("headers")
    @classmethod
    def validate_header_envs(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = [name for name in value.values()
                   if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name)]
        if invalid:
            raise ValueError("header values must name environment variables")
        return value

    def to_pi(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"baseUrl": self.base_url, "api": self.api}
        if self.api_key_env is not None:
            payload["apiKey"] = self.api_key_env
        if self.name is not None:
            payload["name"] = self.name
        if self.headers:
            payload["headers"] = dict(self.headers)
        if self.auth_header is not None:
            payload["authHeader"] = self.auth_header
        if self.compat:
            payload["compat"] = dict(self.compat)
        return payload


class ModelDefinition(FrozenConfigModel):
    """A reusable model alias and the Pi metadata needed to register it."""

    provider: str
    id: str
    name: str | None = None
    api: str | None = None
    base_url: str | None = None
    reasoning: bool = True
    input: list[ModelInput] = Field(default_factory=lambda: ["text"])
    context_window: int = Field(default=128_000, ge=1)
    max_tokens: int = Field(default=16_384, ge=1)
    thinking_level_map: dict[PiThinkingLevel, str | None] | None = None
    sampling_params: dict[str, Any] = Field(default_factory=dict)
    cost: ModelCost | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    compat: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", "id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if "@" in value:
            raise ValueError("must not contain '@'; reasoning belongs on each stage seat")
        return value

    @field_validator("input")
    @classmethod
    def validate_input(cls, value: list[ModelInput]) -> list[ModelInput]:
        if "text" not in value:
            raise ValueError("must include text")
        return list(dict.fromkeys(value))

    @field_validator("thinking_level_map", mode="before")
    @classmethod
    def normalize_off_map_key(cls, value: Any) -> Any:
        # PyYAML follows YAML 1.1 and parses an unquoted `off` key as False.
        if isinstance(value, dict) and False in value:
            value = {("off" if key is False else key): item for key, item in value.items()}
        return value

    @field_validator("headers")
    @classmethod
    def validate_header_envs(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = [name for name in value.values()
                   if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name)]
        if invalid:
            raise ValueError("header values must name environment variables")
        return value

    @property
    def full_id(self) -> str:
        return f"{self.provider}/{self.id}"

    def supports(self, level: ReasoningLevel) -> bool:
        if level == "off":
            return True
        if not self.reasoning:
            return False
        if self.thinking_level_map is None:
            return level != "xhigh"
        if level in self.thinking_level_map:
            return self.thinking_level_map[level] is not None
        return level != "xhigh"

    def to_pi(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name or self.id,
            "reasoning": self.reasoning,
            "input": list(self.input),
            "contextWindow": self.context_window,
            "maxTokens": self.max_tokens,
        }
        if self.api is not None:
            payload["api"] = self.api
        if self.base_url is not None:
            payload["baseUrl"] = self.base_url
        if self.thinking_level_map is not None:
            payload["thinkingLevelMap"] = dict(self.thinking_level_map)
        if self.sampling_params:
            payload["samplingParams"] = dict(self.sampling_params)
        if self.cost is not None:
            payload["cost"] = self.cost.to_pi()
        if self.headers:
            payload["headers"] = dict(self.headers)
        if self.compat:
            payload["compat"] = dict(self.compat)
        return payload


class MajicsSeat(FrozenConfigModel):
    model: str
    reasoning: ReasoningLevel

    @field_validator("reasoning", mode="before")
    @classmethod
    def normalize_off(cls, value: Any) -> Any:
        # Let YAML authors write the natural `reasoning: off` without quotes.
        return "off" if value is False else value

    @field_validator("model")
    @classmethod
    def validate_model_reference(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if "@" in value:
            raise ValueError("put the reasoning level in the separate 'reasoning' field")
        return value


class MajicsStage(FrozenConfigModel):
    panel: list[MajicsSeat] = Field(min_length=2)
    judge: MajicsSeat


class MajicsConfig(FrozenConfigModel):
    version: Literal[1] = 1
    providers: dict[str, ProviderConfig] = Field(min_length=1)
    models: dict[str, ModelDefinition] = Field(min_length=1)
    review: MajicsStage
    propose: MajicsStage
    _credential_values: dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> "MajicsConfig":
        for provider in self.providers:
            if not provider.strip() or "/" in provider or "@" in provider:
                raise ValueError(f'invalid provider name "{provider}"')

        full_ids: dict[str, str] = {}
        for alias, model in self.models.items():
            if not alias.strip() or "/" in alias or "@" in alias:
                raise ValueError(f'invalid model alias "{alias}"')
            if model.provider not in self.providers:
                raise ValueError(
                    f'model "{alias}" references unknown provider "{model.provider}"'
                )
            if model.full_id in full_ids:
                other = full_ids[model.full_id]
                raise ValueError(
                    f'model aliases "{other}" and "{alias}" both define {model.full_id}'
                )
            full_ids[model.full_id] = alias

        for stage_name, stage in (("review", self.review), ("propose", self.propose)):
            seats = [*stage.panel, stage.judge]
            for index, seat in enumerate(seats):
                model = self.resolve_model(seat.model)
                if not model.supports(seat.reasoning):
                    position = "judge" if index == len(stage.panel) else f"panel[{index}]"
                    raise ValueError(
                        f'{stage_name}.{position} requests unsupported reasoning level '
                        f'"{seat.reasoning}" from model "{seat.model}"'
                    )
        return self

    def resolve_model(self, reference: str) -> ModelDefinition:
        if reference in self.models:
            return self.models[reference]
        matches = [model for model in self.models.values() if model.full_id == reference]
        if len(matches) == 1:
            return matches[0]
        raise ValueError(
            f'unknown model reference "{reference}"; use a key from "models" or a declared provider/model id'
        )

    def seat_spec(self, seat: MajicsSeat) -> dict[str, str]:
        return {"id": self.resolve_model(seat.model).full_id, "reasoning": seat.reasoning}

    def seat_label(self, seat: MajicsSeat) -> str:
        spec = self.seat_spec(seat)
        return f'{spec["id"]}@{spec["reasoning"]}'

    def provider_hosts(self) -> list[str]:
        urls = [provider.base_url for provider in self.providers.values()]
        urls.extend(model.base_url for model in self.models.values() if model.base_url)
        return list(dict.fromkeys(
            host for url in urls if (host := urlparse(url).hostname)
        ))

    def models_json(self) -> str:
        providers: dict[str, dict[str, Any]] = {}
        for provider_name, provider in self.providers.items():
            payload = provider.to_pi()
            models = [
                model.to_pi() for model in self.models.values()
                if model.provider == provider_name
            ]
            if models:
                payload["models"] = models
            providers[provider_name] = payload
        return json.dumps({"providers": providers}, indent=2) + "\n"

    def _credential_names(self) -> set[str]:
        names: set[str] = set()
        for provider in self.providers.values():
            if provider.api_key_env:
                names.add(provider.api_key_env)
            names.update(provider.headers.values())
        for model in self.models.values():
            names.update(model.headers.values())
        return names

    def credential_env(self) -> dict[str, str]:
        """Resolve only credential variables referenced by the Pi config."""
        names = self._credential_names()
        source = {**os.environ, **self._credential_values}
        missing = sorted(name for name in names if not source.get(name))
        if missing:
            raise ValueError(
                "missing MAJICS credential environment variable(s): "
                + ", ".join(missing)
            )
        return {name: source[name] for name in sorted(names)}

    def credential_templates(self) -> dict[str, str]:
        """Harbor-safe references that resolve from the host only at runtime."""
        return {name: f"${{{name}}}" for name in sorted(self._credential_names())}

    def with_credentials(self, environment: Mapping[str, str]) -> "MajicsConfig":
        """Bind runtime-only credential values without serializing them."""
        bound = self.model_copy()
        bound._credential_values = {
            name: environment[name]
            for name in self._credential_names()
            if name in environment
        }
        return bound


class ServiceConfig(FrozenConfigModel):
    """HTTP service, durable state, and dashboard configuration."""

    data_dir: Path = Path("data")
    token: str = "dev-token"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    announce_host: str = "host.docker.internal"
    ui_dir: Path = Path("apps/web/dist")
    expose_write_token: bool = True


class TargetConfig(FrozenConfigModel):
    """Default model shown for the target agent."""

    model: str = "openai/gpt-5.4-mini"


class OptimizationConfig(FrozenConfigModel):
    """Host-side optimization and retry limits."""

    max_attempts: int = Field(default=3, ge=1)
    stage_timeout_s: int = Field(default=3600, ge=1)


class HoneConfig(FrozenConfigModel):
    """The complete, versioned ``hone.yaml`` document."""

    version: Literal[1] = 1
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    majics: MajicsConfig

    @model_validator(mode="after")
    def validate_target_provider(self) -> "HoneConfig":
        provider, separator, model = self.target.model.partition("/")
        if not separator or not provider or not model:
            raise ValueError('target.model must use "provider/model" form')
        if provider not in self.majics.providers:
            raise ValueError(
                f'target.model references unknown provider "{provider}"'
            )
        return self

    @property
    def pipeline_label(self) -> str:
        return (
            f"MAJICS · review[{len(self.majics.review.panel)} → "
            f"{self.majics.seat_label(self.majics.review.judge)}] · "
            f"propose[{len(self.majics.propose.panel)} → "
            f"{self.majics.seat_label(self.majics.propose.judge)}]"
        )
