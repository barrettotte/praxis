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


def load_catalog_directory(environ: Mapping[str, str] | None = None) -> Path:
    """Load the read-only local catalog path, with the sibling repository as default."""
    source = os.environ if environ is None else environ
    configured_path = source.get("PRAXIS_DATA_DIR", "").strip()
    return Path(configured_path) if configured_path else DEFAULT_CATALOG_DIRECTORY
