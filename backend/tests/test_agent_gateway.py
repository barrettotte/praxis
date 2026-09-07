import json
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import Tool as MCPTool
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.hooks import BeforeToolCallEvent
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport

from praxis.agent import gateway, generation
from praxis.agent.budget import ToolCallBudget
from praxis.agent.evidence import EvidenceState
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain import (
    EvidenceCitation,
    ProjectCandidate,
    ProjectCandidateSet,
    validate_candidate_output,
)
from praxis.domain.prompt_safety import SensitiveInputError


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


def gateway_candidate_records() -> list[dict[str, object]]:
    candidates = candidate_set().candidates
    return [
        {
            "title": candidate.title,
            "summary": candidate.summary,
            "rationale": candidate.rationale,
            "estimated_scope": candidate.estimated_scope,
            "primary_technology": candidate.technologies[0],
            "first_milestone": candidate.first_milestone,
            "evidence_index": 1,
            "generated_connection": candidate.evidence_citations[0].generated_connection,
        }
        for candidate in candidates
    ]


def gateway_candidate_output(
    records: list[dict[str, object]] | None = None,
) -> generation.CandidateDraftSet:
    return generation.CandidateDraftSet.model_validate(
        {"candidates": records if records is not None else gateway_candidate_records()}
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


@pytest.mark.parametrize("source", ["goal", "catalog"])
def test_gateway_screens_content_before_model_invocation(source: str) -> None:
    agent = MagicMock()
    context, client = stub_gateway_session(agent)
    marker = "api_key=synthetic-credential"
    if source == "catalog":
        client.call_tool_sync.return_value = {
            "status": "success",
            "content": [{"text": json.dumps({"results": [{"title": marker}]})}],
        }
    with (
        patch.object(gateway, "gateway_agent_session", return_value=context) as session,
        pytest.raises(SensitiveInputError),
    ):
        gateway.invoke_gateway_agent(
            marker if source == "goal" else "compiler",
            AgentSettings(model_id="amazon.nova-pro-v1:0", region="us-east-1"),
            gateway_settings(),
        )
    agent.assert_not_called()
    if source != "catalog":
        session.assert_not_called()


def test_validate_gateway_tools_requires_exact_catalog_boundary() -> None:
    tools = catalog_tools()
    assert gateway.validate_gateway_tools(tools) == tuple(tools)

    with pytest.raises(
        generation.CandidatePlanningError, match="expected read-only catalog boundary"
    ):
        gateway.validate_gateway_tools(catalog_tools()[:-1])

    unexpected = MCPAgentTool(
        MCPTool(
            name="praxis-dev-catalog___delete_catalog",
            description="Unexpected mutating tool.",
            inputSchema={"type": "object"},
        ),
        cast("MCPClient", MagicMock()),
    )
    with pytest.raises(
        generation.CandidatePlanningError, match="expected read-only catalog boundary"
    ):
        gateway.validate_gateway_tools([*catalog_tools(), unexpected])


def test_candidate_schema_requires_three_structured_drafts() -> None:
    schema = generation.CandidateDraftSet.model_json_schema()
    assert set(schema["properties"]) == {"candidates"}
    candidates = schema["properties"]["candidates"]
    assert candidates["type"] == "array"
    assert candidates["minItems"] == candidates["maxItems"] == 3


def test_gateway_candidate_schema_rejects_incomplete_inner_candidate_sets() -> None:
    records = gateway_candidate_records()
    records.pop()

    with pytest.raises(ValueError, match=r"List should have at least 3 items"):
        gateway_candidate_output(records)


def test_gateway_candidate_schema_reports_safe_inner_field_errors() -> None:
    records = gateway_candidate_records()
    records[0]["estimated_scope"] = "Small"

    with pytest.raises(
        ValueError,
        match=(
            r"Input should be "
            r"'weekend', 'multi-week' or 'multi-month'"
        ),
    ) as error:
        gateway_candidate_output(records)

    assert "Small" not in str(error.value)


def test_gateway_candidate_schema_bounds_verbose_generated_connections() -> None:
    records = gateway_candidate_records()
    records[0]["generated_connection"] = "relevant motor evidence " * 20

    output = gateway_candidate_output(records)
    candidates = validate_candidate_output(output.as_payload(("book:0f5ba253568e4836",)))
    connection = candidates.candidates[0].evidence_citations[0].generated_connection

    assert len(connection) <= generation.MAX_GENERATED_CONNECTION_LENGTH
    assert connection.endswith("evidence")


def test_gateway_agent_session_keeps_client_open_while_constructing_agent() -> None:
    fake_client = MagicMock()
    tools = catalog_tools()
    fake_client.list_tools_sync.return_value = tools
    agent_settings = AgentSettings(
        model_id="amazon.nova-pro-v1:0",
        region="us-east-1",
        guardrail_id="guardrail-123",
        guardrail_version="7",
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
        generation.catalog_query(
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
                    "CandidateDraftSet": SimpleNamespace(call_count=1),
                }
            )

    def invoke_stub(_prompt: object, **kwargs: object) -> StubAgentResult:
        invocation_state = cast("dict[str, object]", kwargs["invocation_state"])
        budget = ToolCallBudget(
            maximum_calls=agent_settings.max_tool_calls,
            tool_names=frozenset(gateway.EXPECTED_CATALOG_TOOLS),
        )
        for tool_name in gateway.EXPECTED_CATALOG_TOOLS:
            budget.before_tool_call(
                BeforeToolCallEvent(
                    agent=cast("Agent", fake_agent),
                    selected_tool=None,
                    tool_use={"name": tool_name, "input": {}, "toolUseId": tool_name},
                    invocation_state=invocation_state,
                )
            )
        return StubAgentResult()

    fake_agent = MagicMock(side_effect=invoke_stub)
    session, client = stub_gateway_session(fake_agent)
    agent_settings = AgentSettings(
        model_id="amazon.nova-pro-v1:0",
        region="us-east-1",
        guardrail_id="guardrail-123",
        guardrail_version="7",
    )

    with (
        patch.object(gateway, "gateway_agent_session", return_value=session),
    ):
        result = gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            agent_settings,
            gateway_settings(),
        )

    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once()
    client.call_tool_sync.assert_called_once_with(
        tool_use_id="praxis-initial-search",
        name="praxis-dev-catalog___search_catalog",
        arguments={"query": "recommend compiler project", "limit": 3},
        read_timeout_seconds=None,
    )
    generation_prompt = cast("list[dict[str, object]]", fake_agent.call_args.args[0])
    assert generation_prompt[0] == {
        "guardContent": {"text": {"text": "Recommend a compiler project"}}
    }
    application_context = cast("str", generation_prompt[1]["text"])
    assert '"evidence_id":"book:0f5ba253568e4836"' in application_context
    assert fake_agent.call_args.kwargs["structured_output_model"] is generation.CandidateDraftSet
    assert fake_agent.call_args.kwargs["limits"] == {"turns": 6}
    assert result.candidates == candidate_set()
    assert result.tool_calls == (("search_catalog", 1),)
    assert [item.model_dump(mode="json") for item in result.evidence] == [
        {
            "evidence_id": "book:0f5ba253568e4836",
            "kind": "book",
            "title": "Compiler Backend Development",
            "author": None,
            "year": 2025,
            "category": None,
            "tags": [],
        }
    ]


def test_validate_gateway_candidate_result_applies_domain_validation() -> None:
    records = gateway_candidate_records()
    records[1]["title"] = records[0]["title"]
    duplicate = gateway_candidate_output(records)
    result = cast("AgentResult", SimpleNamespace(structured_output=duplicate))

    with pytest.raises(generation.CandidatePlanningError, match="invalid structured"):
        generation.validate_candidate_result(
            result,
            evidence_state("book:0f5ba253568e4836"),
        )


def test_validate_gateway_candidate_result_rejects_empty_evidence() -> None:
    result = cast("AgentResult", SimpleNamespace(structured_output=candidate_set()))

    with pytest.raises(generation.CandidatePlanningError, match="No catalog evidence"):
        generation.validate_candidate_result(result, evidence_state())


def test_validate_gateway_candidate_result_rejects_conflicting_evidence() -> None:
    evidence_id = "book:0f5ba253568e4836"
    result = cast("AgentResult", SimpleNamespace(structured_output=candidate_set()))

    with pytest.raises(generation.CandidatePlanningError, match="conflicting evidence"):
        generation.validate_candidate_result(
            result,
            evidence_state(evidence_id, conflicts=frozenset({evidence_id})),
        )


def test_gateway_citations_cannot_expand_the_allowed_retrieval_context() -> None:
    output = gateway_candidate_output(gateway_candidate_records())
    result = cast("AgentResult", SimpleNamespace(structured_output=output))
    state = EvidenceState(
        evidence_ids=frozenset({"project:1111111111111111"}),
        conflicting_ids=frozenset(),
        ordered_evidence_ids=("book:0f5ba253568e4836",),
    )
    with pytest.raises(generation.CandidatePlanningError, match="was not retrieved"):
        generation.validate_candidate_result(result, state)


def test_validate_gateway_candidate_result_maps_evidence_positions_to_exact_ids() -> None:
    records = gateway_candidate_records()
    records[1]["evidence_index"] = 2
    records[2]["evidence_index"] = 3
    output = gateway_candidate_output(records)
    result = cast("AgentResult", SimpleNamespace(structured_output=output))
    evidence_ids = (
        "book:0000000000000001",
        "project:0000000000000002",
        "byte:0000000000000003",
    )

    candidates = generation.validate_candidate_result(result, evidence_state(*evidence_ids))

    assert (
        tuple(candidate.evidence_citations[0].evidence_id for candidate in candidates.candidates)
        == evidence_ids
    )


def test_validate_gateway_candidate_result_accepts_native_candidate_set() -> None:
    output = generation.CandidateDraftSet.model_validate(
        {"candidates": gateway_candidate_records()}
    )
    result = cast("AgentResult", SimpleNamespace(structured_output=output))

    candidates = generation.validate_candidate_result(
        result,
        evidence_state("book:0f5ba253568e4836"),
    )

    assert candidates == candidate_set()


def test_validate_gateway_candidate_result_rejects_unavailable_evidence_position() -> None:
    records = gateway_candidate_records()
    records[0]["evidence_index"] = 2
    result = cast(
        "AgentResult",
        SimpleNamespace(structured_output=gateway_candidate_output(records)),
    )

    with pytest.raises(generation.CandidatePlanningError, match="unavailable evidence position 2"):
        generation.validate_candidate_result(
            result,
            evidence_state("book:0f5ba253568e4836"),
        )


def test_invoke_gateway_agent_reports_exhausted_model_turn_budget() -> None:
    fake_agent = MagicMock(
        return_value=SimpleNamespace(
            stop_reason="limit_turns",
            structured_output=None,
            metrics=SimpleNamespace(
                tool_metrics={
                    "CandidateDraftSet": SimpleNamespace(call_count=3),
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
                                    "Validation failed for CandidateDraftSet. "
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
            generation.CandidatePlanningError,
            match=(
                r"model-turn budget.*CandidateDraftSet=3, search_catalog=2[\s\S]*"
                r"candidates -> 1 -> title.*duplicate title"
            ),
        ),
    ):
        gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            AgentSettings(model_id="amazon.nova-pro-v1:0", region="us-east-1"),
            gateway_settings(),
        )
