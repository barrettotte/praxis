import json
from pathlib import Path

import pytest

from praxis.agent import gateway_smoke
from praxis.agent.gateway import GatewayAgentError, GatewayAgentRun
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet


def agent_settings() -> AgentSettings:
    return AgentSettings(model_id="amazon.nova-micro-v1:0", region="us-east-1")


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def candidate_set() -> ProjectCandidateSet:
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides relevant implementation context.",
                estimated_scope="multi-week",
                technologies=["Python"],
                first_milestone="Implement one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0f5ba253568e4836",
                        generated_connection="The book covers compiler backend development.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
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
        candidates=candidate_set(),
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

    assert result["candidates"] == candidate_set().model_dump(mode="json")
    assert result["tool_calls"] == [{"count": 1, "name": "praxis-dev-catalog___search_catalog"}]
    assert json.loads((tmp_path / "strands-gateway-agent-run.json").read_text()) == {
        "all_candidates_cited": True,
        "authentication": "AWS_IAM",
        "candidate_count": 3,
        "catalog_result_budget": 20,
        "client": "Strands Agent with MCPClient",
        "evidence_citation_count": 3,
        "model_id": "amazon.nova-micro-v1:0",
        "tool_call_budget": 4,
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
            candidates=candidate_set(),
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
