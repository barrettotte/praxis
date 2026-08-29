"""Tests for runtime configuration."""

from pathlib import Path

import pytest

from praxis.config import (
    DEFAULT_CATALOG_DIRECTORY,
    DEFAULT_MAX_TOOL_CALLS,
    AgentSettings,
    GatewaySettings,
    SettingsError,
    load_catalog_directory,
    load_gateway_settings,
    load_settings,
)


def test_load_settings() -> None:
    """Required settings are read without embedding model configuration in code."""
    settings = load_settings(
        {
            "PRAXIS_MODEL_ID": "example.model-v1:0",
            "AWS_REGION": "us-east-1",
        }
    )

    assert settings == AgentSettings(
        model_id="example.model-v1:0",
        region="us-east-1",
        max_tool_calls=DEFAULT_MAX_TOOL_CALLS,
    )


def test_load_settings_reads_tool_call_budget() -> None:
    settings = load_settings(
        {
            "PRAXIS_MODEL_ID": "example.model-v1:0",
            "AWS_REGION": "us-east-1",
            "PRAXIS_MAX_TOOL_CALLS": "2",
        }
    )

    assert settings.max_tool_calls == 2


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_load_settings_rejects_invalid_tool_call_budget(value: str) -> None:
    with pytest.raises(SettingsError, match="PRAXIS_MAX_TOOL_CALLS must be a positive integer"):
        load_settings(
            {
                "PRAXIS_MODEL_ID": "example.model-v1:0",
                "AWS_REGION": "us-east-1",
                "PRAXIS_MAX_TOOL_CALLS": value,
            }
        )


@pytest.mark.parametrize("missing_name", ["PRAXIS_MODEL_ID", "AWS_REGION"])
def test_load_settings_requires_configuration(missing_name: str) -> None:
    """Missing runtime configuration produces an actionable error."""
    environ = {
        "PRAXIS_MODEL_ID": "example.model-v1:0",
        "AWS_REGION": "us-east-1",
    }
    del environ[missing_name]

    with pytest.raises(SettingsError, match=missing_name):
        load_settings(environ)


def test_load_gateway_settings_with_optional_local_profile() -> None:
    settings = load_gateway_settings(
        {
            "PRAXIS_GATEWAY_URL": "https://example.gateway.test/mcp",
            "AWS_REGION": "us-east-1",
            "AWS_PROFILE": "praxis-dev",
        }
    )

    assert settings == GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def test_load_gateway_settings_omits_runtime_profile() -> None:
    settings = load_gateway_settings(
        {
            "PRAXIS_GATEWAY_URL": "https://example.gateway.test/mcp",
            "AWS_REGION": "us-east-1",
        }
    )

    assert settings.profile is None


def test_load_catalog_directory_uses_configured_path() -> None:
    assert load_catalog_directory({"PRAXIS_DATA_DIR": "data/fixtures"}) == Path("data/fixtures")


def test_load_catalog_directory_defaults_to_sibling_source() -> None:
    assert load_catalog_directory({}) == DEFAULT_CATALOG_DIRECTORY
