import json
from pathlib import Path

import pytest

from praxis.agent import gateway_smoke
from praxis.agent.gateway import GatewayAgentError, GatewayAgentRun
from praxis.config import AgentSettings, GatewaySettings


def agent_settings() -> AgentSettings:
    return AgentSettings(model_id="amazon.nova-micro-v1:0", region="us-east-1")


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def test_write_deterministic_strands_discovery_evidence(tmp_path: Path) -> None:
    evidence_path = gateway_smoke.write_evidence(
        tmp_path,
        (
            "praxis-dev-catalog___get_catalog_item",
            "praxis-dev-catalog___score_project_candidates",
            "praxis-dev-catalog___search_catalog",
            "praxis-dev-catalog___summarize_experience",
        ),
    )

    assert json.loads(evidence_path.read_text()) == {
        "authentication": "AWS_IAM",
        "client": "Strands MCPClient",
        "method": "tools/list",
        "tools": [
            "praxis-dev-catalog___get_catalog_item",
            "praxis-dev-catalog___score_project_candidates",
            "praxis-dev-catalog___search_catalog",
            "praxis-dev-catalog___summarize_experience",
        ],
    }


def test_run_invokes_agent_with_discovered_gateway_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tools = ("praxis-dev-catalog___search_catalog",)
    agent_run = GatewayAgentRun(
        response="Build an LLVM instruction-selection explorer.",
        tool_calls=(("praxis-dev-catalog___search_catalog", 1),),
    )

    def fake_discover(settings: GatewaySettings) -> tuple[str, ...]:
        assert settings == gateway_settings()
        return tools

    def fake_invoke(
        prompt: str,
        configured_agent: AgentSettings,
        configured_gateway: GatewaySettings,
    ) -> GatewayAgentRun:
        assert prompt == "Recommend a compiler project"
        assert configured_agent == agent_settings()
        assert configured_gateway == gateway_settings()
        return agent_run

    monkeypatch.setattr(gateway_smoke, "discover_gateway_tool_names", fake_discover)
    monkeypatch.setattr(gateway_smoke, "invoke_gateway_agent", fake_invoke)

    result = gateway_smoke.run(
        agent_settings(),
        gateway_settings(),
        "Recommend a compiler project",
        tmp_path,
    )

    assert result["response"] == agent_run.response
    assert result["tool_calls"] == [{"count": 1, "name": "praxis-dev-catalog___search_catalog"}]
    assert json.loads((tmp_path / "strands-gateway-agent-run.json").read_text()) == {
        "authentication": "AWS_IAM",
        "client": "Strands Agent with MCPClient",
        "model_id": "amazon.nova-micro-v1:0",
        "response_received": True,
        "tool_calls": [{"count": 1, "name": "praxis-dev-catalog___search_catalog"}],
    }


def test_run_rejects_an_agent_response_without_gateway_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_discover(_settings: GatewaySettings) -> tuple[str, ...]:
        return ("praxis-dev-catalog___search_catalog",)

    def fake_invoke(
        _prompt: str,
        _agent_settings: AgentSettings,
        _gateway_settings: GatewaySettings,
    ) -> GatewayAgentRun:
        return GatewayAgentRun(
            response="Unsupported recommendation",
            tool_calls=(),
        )

    monkeypatch.setattr(
        gateway_smoke,
        "discover_gateway_tool_names",
        fake_discover,
    )
    monkeypatch.setattr(
        gateway_smoke,
        "invoke_gateway_agent",
        fake_invoke,
    )

    with pytest.raises(GatewayAgentError, match="did not call"):
        gateway_smoke.run(agent_settings(), gateway_settings())
