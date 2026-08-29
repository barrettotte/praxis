"""Runtime configuration for the Praxis agent."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CATALOG_DIRECTORY = Path("../barrettotte.github.io/data")


class SettingsError(RuntimeError):
    """Raised when required runtime configuration is absent."""


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Configuration required to invoke the Bedrock-backed agent."""

    model_id: str
    region: str


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    """Configuration for the IAM-authenticated AgentCore Gateway client."""

    url: str
    region: str
    profile: str | None = None


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name, "").strip()
    if not value:
        message = f"{name} is required; copy .env.example to .env and set it"
        raise SettingsError(message)
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> AgentSettings:
    """Load agent settings from environment variables."""
    source = os.environ if environ is None else environ
    return AgentSettings(
        model_id=_required(source, "PRAXIS_MODEL_ID"),
        region=_required(source, "AWS_REGION"),
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


def load_catalog_directory(environ: Mapping[str, str] | None = None) -> Path:
    """Load the read-only local catalog path, with the sibling repository as default."""
    source = os.environ if environ is None else environ
    configured_path = source.get("PRAXIS_DATA_DIR", "").strip()
    return Path(configured_path) if configured_path else DEFAULT_CATALOG_DIRECTORY
