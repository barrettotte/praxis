"""Tests for runtime configuration."""

import pytest

from praxis.config import AgentSettings, SettingsError, load_settings


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
