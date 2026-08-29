import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import Tool as MCPTool
from strands.agent.agent_result import AgentResult
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport
from strands.types.exceptions import EventLoopException

from praxis.agent import gateway
from praxis.agent.budget import ToolCallBudgetError
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def catalog_tools() -> list[MCPAgentTool]:
    client = cast("MCPClient", MagicMock())
    return [
        MCPAgentTool(
            MCPTool(
                name=f"praxis-dev-catalog___{name}",
                description=f"Invoke {name}.",
                inputSchema={"type": "object"},
            ),
            client,
        )
        for name in gateway.EXPECTED_CATALOG_TOOLS
    ]


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


def test_create_gateway_client_uses_sigv4_and_catalog_allowlist() -> None:
    with (
        patch.object(gateway, "aws_iam_streamablehttp_client") as transport_type,
        patch.object(gateway, "MCPClient") as client_type,
    ):
        client = gateway.create_gateway_client(gateway_settings())
        transport = cast("Callable[[], MCPTransport]", client_type.call_args.args[0])
        transport_result = transport()

    assert client is client_type.return_value
    assert transport_result is transport_type.return_value
    transport_type.assert_called_once_with(
        endpoint="https://example.gateway.test/mcp",
        aws_service="bedrock-agentcore",
        aws_region="us-east-1",
        aws_profile="praxis-dev",
        timeout=20,
        sse_read_timeout=30,
    )
    client_type.assert_called_once()
    options = client_type.call_args.kwargs
    assert options["startup_timeout"] == 20
    assert options["application_name"] == "praxis-agent"
    allowed = cast("list[re.Pattern[str]]", options["tool_filters"]["allowed"])
    assert all(allowed[0].fullmatch(tool.tool_name) for tool in catalog_tools())
    assert not allowed[0].fullmatch("praxis-dev-github___create_issues")


def test_validate_gateway_tools_requires_exact_catalog_boundary() -> None:
    tools = catalog_tools()
    assert gateway.validate_gateway_tools(tools) == tuple(tools)

    with pytest.raises(gateway.GatewayAgentError, match="expected read-only catalog boundary"):
        gateway.validate_gateway_tools(catalog_tools()[:-1])


def test_gateway_agent_session_keeps_client_open_while_constructing_agent() -> None:
    fake_client = MagicMock()
    tools = catalog_tools()
    fake_client.list_tools_sync.return_value = tools
    agent_settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with (
        patch.object(gateway, "create_gateway_client", return_value=fake_client),
        patch.object(gateway, "create_agent") as create_agent,
        gateway.gateway_agent_session(agent_settings, gateway_settings()) as agent,
    ):
        assert agent is create_agent.return_value

    fake_client.__enter__.assert_called_once_with()
    fake_client.__exit__.assert_called_once()
    model_tools = cast("tuple[MCPAgentTool, ...]", create_agent.call_args.kwargs["tools"])
    assert tuple(tool.tool_name for tool in model_tools) == gateway.EXPECTED_CATALOG_TOOLS
    assert tuple(tool.mcp_tool.name for tool in model_tools) == tuple(
        tool.tool_name for tool in tools
    )


def test_invoke_gateway_agent_keeps_session_open_during_model_invocation() -> None:
    class StubAgentResult:
        def __init__(self) -> None:
            self.structured_output = candidate_set()
            self.metrics = SimpleNamespace(
                tool_metrics={
                    "search_catalog": SimpleNamespace(call_count=1),
                    "get_catalog_item": SimpleNamespace(call_count=0),
                    "ProjectCandidateSet": SimpleNamespace(call_count=1),
                }
            )

    fake_agent = MagicMock()
    fake_agent.return_value = StubAgentResult()
    session = MagicMock()
    session.__enter__.return_value = fake_agent
    agent_settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with patch.object(gateway, "gateway_agent_session", return_value=session):
        result = gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            agent_settings,
            gateway_settings(),
        )

    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once()
    fake_agent.assert_called_once_with(
        "Recommend a compiler project",
        structured_output_model=ProjectCandidateSet,
    )
    assert result.candidates == candidate_set()
    assert result.tool_calls == (("search_catalog", 1),)


def test_validate_gateway_candidate_result_rejects_uncited_candidates() -> None:
    invalid_output = MagicMock()
    invalid_output.model_dump.return_value = {
        "candidates": [
            {
                "title": f"Candidate {number}",
                "summary": "Build a focused compiler project.",
                "rationale": "It appears relevant.",
                "estimated_scope": "multi-week",
                "technologies": ["Python"],
                "first_milestone": "Implement one instruction-selection rule.",
            }
            for number in range(1, 4)
        ]
    }
    result = cast("AgentResult", SimpleNamespace(structured_output=invalid_output))

    with pytest.raises(gateway.GatewayAgentError, match="invalid structured"):
        gateway.validate_gateway_candidate_result(result)


def test_invoke_gateway_agent_reports_exhausted_tool_call_budget() -> None:
    budget_error = ToolCallBudgetError("budget exhausted")
    fake_agent = MagicMock(side_effect=EventLoopException(budget_error))
    session = MagicMock()
    session.__enter__.return_value = fake_agent

    with (
        patch.object(gateway, "gateway_agent_session", return_value=session),
        pytest.raises(gateway.GatewayAgentError, match="budget exhausted"),
    ):
        gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            AgentSettings(model_id="amazon.nova-micro-v1:0", region="us-east-1"),
            gateway_settings(),
        )
