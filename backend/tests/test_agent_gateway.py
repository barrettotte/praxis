import json
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
from praxis.agent.evidence import EvidenceState
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


def gateway_candidate_output() -> gateway.GatewayCandidateOutput:
    candidates = candidate_set().candidates
    return gateway.GatewayCandidateOutput.model_validate(
        {
            f"candidate_{number}_{field}": value
            for number, candidate in enumerate(candidates, start=1)
            for field, value in {
                "title": candidate.title,
                "summary": candidate.summary,
                "rationale": candidate.rationale,
                "estimated_scope": candidate.estimated_scope,
                "primary_technology": candidate.technologies[0],
                "first_milestone": candidate.first_milestone,
                "evidence_index": 1,
                "generated_connection": candidate.evidence_citations[0].generated_connection,
            }.items()
        },
    )


def evidence_state(*evidence_ids: str, conflicts: frozenset[str] = frozenset()) -> EvidenceState:
    return EvidenceState(
        evidence_ids=frozenset(evidence_ids),
        conflicting_ids=conflicts,
        ordered_evidence_ids=evidence_ids,
    )


def search_result() -> dict[str, object]:
    return {
        "results": [
            {
                "evidence_id": "book:0f5ba253568e4836",
                "kind": "book",
                "title": "Compiler Backend Development",
                "year": 2025,
                "tags": [],
                "score": 10,
            }
        ]
    }


def stub_gateway_session(agent: MagicMock) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    client.call_tool_sync.return_value = {
        "toolUseId": "praxis-initial-search",
        "status": "success",
        "content": [{"text": json.dumps(search_result())}],
    }
    gateway_session = gateway.GatewayAgentSession(
        agent=agent,
        client=client,
        tools=gateway.canonical_gateway_tools(catalog_tools()),
    )
    context = MagicMock()
    context.__enter__.return_value = gateway_session
    return context, client


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
    assert not allowed[0].fullmatch("praxis-dev-catalog___delete_records")


def test_validate_gateway_tools_requires_exact_catalog_boundary() -> None:
    tools = catalog_tools()
    assert gateway.validate_gateway_tools(tools) == tuple(tools)

    with pytest.raises(gateway.GatewayAgentError, match="expected read-only catalog boundary"):
        gateway.validate_gateway_tools(catalog_tools()[:-1])


def test_gateway_candidate_schema_uses_only_flat_scalar_fields() -> None:
    schema = gateway.GatewayCandidateOutput.model_json_schema()

    assert "$defs" not in schema
    assert len(schema["properties"]) == 24
    assert all(
        property_schema.get("type") != "object" for property_schema in schema["properties"].values()
    )


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
        gateway.gateway_agent_session(agent_settings, gateway_settings()) as session,
    ):
        assert session.agent is create_agent.return_value
        assert session.client is fake_client

    fake_client.__enter__.assert_called_once_with()
    fake_client.__exit__.assert_called_once()
    model_tools = cast("tuple[MCPAgentTool, ...]", create_agent.call_args.kwargs["tools"])
    assert tuple(tool.tool_name for tool in model_tools) == gateway.EXPECTED_CATALOG_TOOLS
    assert tuple(tool.mcp_tool.name for tool in model_tools) == tuple(
        tool.tool_name for tool in tools
    )


def test_catalog_query_preserves_first_eight_meaningful_terms() -> None:
    assert (
        gateway.catalog_query(
            "Build a compiler backend in Python with LLVM and WebAssembly for learning"
        )
        == "build compiler backend python llvm webassembly learning"
    )


def test_invoke_gateway_agent_keeps_session_open_during_model_invocation() -> None:
    class StubAgentResult:
        def __init__(self) -> None:
            self.stop_reason = "end_turn"
            self.structured_output = gateway_candidate_output()
            self.metrics = SimpleNamespace(
                tool_metrics={
                    "search_catalog": SimpleNamespace(call_count=0),
                    "get_catalog_item": SimpleNamespace(call_count=0),
                    "GatewayCandidateOutput": SimpleNamespace(call_count=1),
                }
            )

    def invoke_stub(_prompt: str, **kwargs: object) -> StubAgentResult:
        cast("dict[str, object]", kwargs["invocation_state"]).clear()
        return StubAgentResult()

    fake_agent = MagicMock(side_effect=invoke_stub)
    session, client = stub_gateway_session(fake_agent)
    agent_settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with (
        patch.object(gateway, "gateway_agent_session", return_value=session),
    ):
        result = gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            agent_settings,
            gateway_settings(),
            memory_context=('{"kind":"preference","text":"Prefer weekend scope."}',),
        )

    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once()
    client.call_tool_sync.assert_called_once_with(
        tool_use_id="praxis-initial-search",
        name="praxis-dev-catalog___search_catalog",
        arguments={"query": "recommend compiler project", "limit": 3},
        read_timeout_seconds=None,
    )
    generation_prompt = cast("str", fake_agent.call_args.args[0])
    assert generation_prompt.startswith("Recommend a compiler project\n\n")
    assert '"evidence_id":"book:0f5ba253568e4836"' in generation_prompt
    assert "user-authored preferences and prior decisions" in generation_prompt
    assert "Prefer weekend scope" in generation_prompt
    assert fake_agent.call_args.kwargs["structured_output_model"] is gateway.GatewayCandidateOutput
    assert fake_agent.call_args.kwargs["limits"] == {"turns": 5}
    assert result.candidates == candidate_set()
    assert result.tool_calls == (("search_catalog", 1),)


def test_validate_gateway_candidate_result_applies_domain_validation() -> None:
    output = gateway_candidate_output()
    duplicate = output.model_copy(update={"candidate_2_title": output.candidate_1_title})
    result = cast("AgentResult", SimpleNamespace(structured_output=duplicate))

    with pytest.raises(gateway.GatewayAgentError, match="invalid structured"):
        gateway.validate_gateway_candidate_result(
            result,
            evidence_state("book:0f5ba253568e4836"),
        )


def test_validate_gateway_candidate_result_rejects_empty_evidence() -> None:
    result = cast("AgentResult", SimpleNamespace(structured_output=candidate_set()))

    with pytest.raises(gateway.GatewayAgentError, match="No catalog evidence"):
        gateway.validate_gateway_candidate_result(result, evidence_state())


def test_validate_gateway_candidate_result_rejects_conflicting_evidence() -> None:
    evidence_id = "book:0f5ba253568e4836"
    result = cast("AgentResult", SimpleNamespace(structured_output=candidate_set()))

    with pytest.raises(gateway.GatewayAgentError, match="conflicting evidence"):
        gateway.validate_gateway_candidate_result(
            result,
            evidence_state(evidence_id, conflicts=frozenset({evidence_id})),
        )


def test_validate_gateway_candidate_result_maps_evidence_positions_to_exact_ids() -> None:
    output = gateway_candidate_output().model_copy(
        update={
            "candidate_2_evidence_index": 2,
            "candidate_3_evidence_index": 3,
        }
    )
    result = cast("AgentResult", SimpleNamespace(structured_output=output))
    evidence_ids = (
        "book:0000000000000001",
        "project:0000000000000002",
        "byte:0000000000000003",
    )

    candidates = gateway.validate_gateway_candidate_result(result, evidence_state(*evidence_ids))

    assert (
        tuple(candidate.evidence_citations[0].evidence_id for candidate in candidates.candidates)
        == evidence_ids
    )


def test_validate_gateway_candidate_result_rejects_unavailable_evidence_position() -> None:
    result = cast(
        "AgentResult",
        SimpleNamespace(
            structured_output=gateway_candidate_output().model_copy(
                update={"candidate_1_evidence_index": 2}
            )
        ),
    )

    with pytest.raises(gateway.GatewayAgentError, match="unavailable evidence position 2"):
        gateway.validate_gateway_candidate_result(
            result,
            evidence_state("book:0f5ba253568e4836"),
        )


def test_invoke_gateway_agent_reports_exhausted_tool_call_budget() -> None:
    budget_error = ToolCallBudgetError("budget exhausted")
    fake_agent = MagicMock(side_effect=EventLoopException(budget_error))
    session, _client = stub_gateway_session(fake_agent)

    with (
        patch.object(gateway, "gateway_agent_session", return_value=session),
        pytest.raises(gateway.GatewayAgentError, match="budget exhausted"),
    ):
        gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            AgentSettings(model_id="amazon.nova-micro-v1:0", region="us-east-1"),
            gateway_settings(),
        )


def test_invoke_gateway_agent_reports_exhausted_model_turn_budget() -> None:
    fake_agent = MagicMock(
        return_value=SimpleNamespace(
            stop_reason="limit_turns",
            structured_output=None,
            metrics=SimpleNamespace(
                tool_metrics={
                    "GatewayCandidateOutput": SimpleNamespace(call_count=3),
                    "search_catalog": SimpleNamespace(call_count=2),
                }
            ),
        )
    )
    fake_agent.messages = [
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "candidate-output",
                        "status": "error",
                        "content": [
                            {
                                "text": (
                                    "Validation failed for GatewayCandidateOutput. "
                                    "Please fix the following errors:\n"
                                    "- Field 'candidates -> 1 -> title': duplicate title"
                                )
                            }
                        ],
                    }
                }
            ],
        }
    ]
    session, _client = stub_gateway_session(fake_agent)

    with (
        patch.object(gateway, "gateway_agent_session", return_value=session),
        pytest.raises(
            gateway.GatewayAgentError,
            match=(
                r"model-turn budget.*GatewayCandidateOutput=3, search_catalog=2[\s\S]*"
                r"candidates -> 1 -> title.*duplicate title"
            ),
        ),
    ):
        gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            AgentSettings(model_id="amazon.nova-micro-v1:0", region="us-east-1"),
            gateway_settings(),
        )
