"""Runtime configuration for the Praxis agent."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CATALOG_DIRECTORY = Path("../barrettotte.github.io/data")
DEFAULT_MAX_CATALOG_RESULTS = 20
DEFAULT_MAX_TOOL_CALLS = 4


class SettingsError(RuntimeError):
    """Raised when required runtime configuration is absent."""


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Configuration required to invoke the Bedrock-backed agent."""

    model_id: str
    region: str
    max_catalog_results: int = DEFAULT_MAX_CATALOG_RESULTS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS

    def __post_init__(self) -> None:
        if self.max_catalog_results < 1 or self.max_tool_calls < 1:
            raise ValueError("agent budgets must be positive")


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    """Configuration for the IAM-authenticated AgentCore Gateway client."""

    url: str
    region: str
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Configuration for actor-scoped AgentCore Memory access."""

    memory_id: str
    region: str
    profile: str | None = None
    top_k: int = 5

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("memory retrieval budget must be positive")


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name, "").strip()
    if not value:
        message = f"{name} is required; copy .env.example to .env and set it"
        raise SettingsError(message)
    return value


def _positive_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw_value = source.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise SettingsError(f"{name} must be a positive integer") from error
    if value < 1:
        raise SettingsError(f"{name} must be a positive integer")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> AgentSettings:
    """Load agent settings from environment variables."""
    source = os.environ if environ is None else environ
    return AgentSettings(
        model_id=_required(source, "PRAXIS_MODEL_ID"),
        region=_required(source, "AWS_REGION"),
        max_catalog_results=_positive_int(
            source,
            "PRAXIS_MAX_CATALOG_RESULTS",
            DEFAULT_MAX_CATALOG_RESULTS,
        ),
        max_tool_calls=_positive_int(
            source,
            "PRAXIS_MAX_TOOL_CALLS",
            DEFAULT_MAX_TOOL_CALLS,
        ),
    )


def load_gateway_settings(environ: Mapping[str, str] | None = None) -> GatewaySettings:
    """Load the Gateway endpoint and optional local AWS profile."""
    source = os.environ if environ is None else environ
    profile = source.get("AWS_PROFILE", "").strip() or None
    return GatewaySettings(
        url=_required(source, "PRAXIS_GATEWAY_URL"),
        region=_required(source, "AWS_REGION"),
        profile=profile,
    )


def load_memory_settings(environ: Mapping[str, str] | None = None) -> MemorySettings:
    """Load the AgentCore Memory identifier and bounded retrieval settings."""
    source = os.environ if environ is None else environ
    profile = source.get("AWS_PROFILE", "").strip() or None
    return MemorySettings(
        memory_id=_required(source, "PRAXIS_MEMORY_ID"),
        region=_required(source, "AWS_REGION"),
        profile=profile,
        top_k=_positive_int(source, "PRAXIS_MEMORY_TOP_K", 5),
    )


def load_catalog_directory(environ: Mapping[str, str] | None = None) -> Path:
    """Load the read-only local catalog path, with the sibling repository as default."""
    source = os.environ if environ is None else environ
    configured_path = source.get("PRAXIS_DATA_DIR", "").strip()
    return Path(configured_path) if configured_path else DEFAULT_CATALOG_DIRECTORY
