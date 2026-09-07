import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import Tool
from pydantic import ValidationError
from strands.tools.mcp import MCPAgentTool, MCPClient
from strands.types.tools import ToolResult

from praxis.agent import gateway, planner
from praxis.agent.generation import (
    CandidateDraftSet,
    CandidatePlanningError,
)
from praxis.agent.local_catalog import LocalCatalogRepository, local_catalog_tools
from praxis.catalog import (
    CatalogEntry,
    CatalogKind,
    CatalogSearchResult,
    InMemoryCatalog,
    SearchCatalogRequest,
    search_catalog,
)
from praxis.catalog.text import catalog_query
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain import Book, EvidenceCitation, ProjectCandidate, ProjectCandidateSet
from praxis.domain.prompt_safety import SensitiveInputError
from praxis.tools.contracts import gateway_tool_definitions

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"
GOAL = "Build a TypeScript electronics notebook"
SETTINGS = AgentSettings(model_id="amazon.nova-pro-v1:0", region="us-east-1")


def candidate_set(evidence_id: str) -> ProjectCandidateSet:
    candidates = [
        ProjectCandidate(
            title=f"Candidate {number}",
            summary="Build a focused project.",
            rationale="It connects the requested goal to prior evidence.",
            estimated_scope="multi-week",
            technologies=["TypeScript"],
            first_milestone="Render one static notebook entry.",
            evidence_citations=[
                EvidenceCitation(
                    evidence_id=evidence_id,
                    generated_connection=(
                        "The record demonstrates related implementation experience."
                    ),
                )
            ],
        )
        for number in range(1, 4)
    ]
    return ProjectCandidateSet(candidates=candidates)


def model_result(evidence_index: int = 1) -> SimpleNamespace:
    output = CandidateDraftSet.model_validate(
        {
            "candidates": [
                {
                    "title": c.title,
                    "summary": c.summary,
                    "rationale": c.rationale,
                    "estimated_scope": c.estimated_scope,
                    "primary_technology": c.technologies[0],
                    "first_milestone": c.first_milestone,
                    "evidence_index": evidence_index,
                    "generated_connection": c.evidence_citations[0].generated_connection,
                }
                for c in candidate_set("book:0000000000000000").candidates
            ]
        }
    )
    return SimpleNamespace(
        structured_output=output,
        stop_reason="end_turn",
        metrics=SimpleNamespace(
            accumulated_usage={"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
            accumulated_metrics={"latencyMs": 10},
            tool_metrics={},
            cycle_count=1,
        ),
    )


@pytest.mark.parametrize("limit", [1, 20])
@pytest.mark.parametrize("model_id", ["amazon.nova-pro-v1:0", "candidate-model"])
def test_local_planner_uses_shared_generation_policy(limit: int, model_id: str) -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    settings = AgentSettings(model_id=model_id, region=SETTINGS.region, max_catalog_results=limit)
    expected = search_catalog(
        catalog, SearchCatalogRequest(query=catalog_query(GOAL), limit=min(3, limit))
    )
    agent = MagicMock(return_value=model_result())
    with patch.object(planner, "create_agent", return_value=agent) as create:
        run = planner.invoke_project_candidates_with_trace(GOAL, catalog, settings)
    assert run.retrieved_evidence_ids == tuple(item.entry.id for item in expected)
    assert run.local_tool_calls == ("search_catalog",)
    assert run.candidates == candidate_set(expected[0].entry.id)
    assert run.generation_metrics is not None
    assert run.generation_metrics.token_usage.total_tokens == 30
    assert agent.call_args.kwargs["structured_output_model"] is CandidateDraftSet
    assert agent.call_args.kwargs["limits"] == {"turns": 6}
    assert "untrusted catalog evidence" in agent.call_args.args[0]
    assert {t.tool_name for t in create.call_args.kwargs["tools"]} == {
        "search_catalog",
        "get_catalog_item",
        "summarize_experience",
        "score_project_candidates",
    }


def test_local_planner_rejects_credentials_before_agent_creation() -> None:
    with patch.object(planner, "create_agent") as create, pytest.raises(SensitiveInputError):
        planner.invoke_project_candidates(
            "api_key=synthetic-credential",
            InMemoryCatalog.from_directory(FIXTURE_DIRECTORY),
            SETTINGS,
        )
    create.assert_not_called()


@pytest.mark.parametrize(
    ("goal", "index", "message"),
    [
        ("zyxwvutsrq", 1, "No catalog evidence"),
        (GOAL, 20, "unavailable evidence position"),
    ],
)
def test_local_planner_rejects_missing_evidence(goal: str, index: int, message: str) -> None:
    agent = MagicMock(return_value=model_result(index))
    with (
        patch.object(planner, "create_agent", return_value=agent),
        pytest.raises(CandidatePlanningError, match=message),
    ):
        planner.invoke_project_candidates(
            goal, InMemoryCatalog.from_directory(FIXTURE_DIRECTORY), SETTINGS
        )
    if goal == "zyxwvutsrq":
        agent.assert_not_called()


def test_local_planner_rejects_conflicting_evidence_before_generation() -> None:
    entries = tuple(
        CatalogSearchResult(
            entry=CatalogEntry(
                id="book:0000000000000000", kind=CatalogKind.BOOK, item=Book(title=title, year=2025)
            ),
            score=10,
        )
        for title in ("Compiler Design", "Different Title")
    )
    agent = MagicMock()
    with (
        patch.object(LocalCatalogRepository, "search", return_value=entries),
        patch.object(planner, "create_agent", return_value=agent),
        pytest.raises(CandidatePlanningError, match="Conflicting catalog facts"),
    ):
        planner.invoke_project_candidates(
            GOAL, InMemoryCatalog.from_directory(FIXTURE_DIRECTORY), SETTINGS
        )
    agent.assert_not_called()


def test_local_tools_reject_invalid_arguments_and_sensitive_records() -> None:
    tools = local_catalog_tools(InMemoryCatalog.from_directory(FIXTURE_DIRECTORY))
    search = next(tool for tool in tools if tool.tool_name == "search_catalog")
    assert search.call({"query": GOAL, "limit": 999}, "invalid")["status"] == "error"
    entries = (
        CatalogSearchResult(
            entry=CatalogEntry(
                id="book:0000000000000000",
                kind=CatalogKind.BOOK,
                item=Book(title="api_key=synthetic-credential", year=2025),
            ),
            score=10,
        ),
    )
    with patch.object(LocalCatalogRepository, "search", return_value=entries):
        response = search.call({"query": GOAL}, "sensitive")
    assert response["status"] == "error"
    assert "synthetic-credential" not in str(response)


@pytest.mark.parametrize("guardrail", [False, True])
def test_local_and_gateway_paths_supply_identical_model_inputs(guardrail: bool) -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    settings = AgentSettings(
        model_id=SETTINGS.model_id,
        region=SETTINGS.region,
        guardrail_id="test-guardrail" if guardrail else None,
        guardrail_version="1" if guardrail else None,
    )
    local_tools = local_catalog_tools(catalog)
    search = next(tool for tool in local_tools if tool.tool_name == "search_catalog")
    client = MagicMock()
    client.list_tools_sync.return_value = [
        MCPAgentTool(
            Tool.model_validate(
                definition.model_dump(mode="json", by_alias=True, exclude_none=True)
                | {"name": f"catalog___{definition.name}"}
            ),
            cast("MCPClient", client),
        )
        for definition in gateway_tool_definitions()
    ]

    def remote_search(**kwargs: object) -> ToolResult:
        return search.call(kwargs["arguments"], str(kwargs["tool_use_id"]))

    client.call_tool_sync.side_effect = remote_search
    local_agent = MagicMock(return_value=model_result())
    remote_agent = MagicMock(return_value=model_result())
    with (
        patch.object(planner, "create_agent", return_value=local_agent) as local_factory,
        patch.object(gateway, "create_agent", return_value=remote_agent) as remote_factory,
        patch.object(gateway, "create_gateway_client", return_value=client),
    ):
        local = planner.invoke_project_candidates_with_trace(GOAL, catalog, settings)
        remote = gateway.invoke_gateway_agent(
            GOAL,
            settings,
            GatewaySettings(url="https://gateway.invalid/mcp", region=settings.region),
        )
    assert local.candidates == remote.candidates
    assert local_agent.call_args == remote_agent.call_args
    assert {t.tool_name: t.tool_spec for t in local_factory.call_args.kwargs["tools"]} == {
        t.tool_name: t.tool_spec for t in remote_factory.call_args.kwargs["tools"]
    }
    client.__exit__.assert_called_once()


def test_local_tool_stream_returns_a_valid_catalog_response() -> None:
    search = next(
        tool
        for tool in local_catalog_tools(InMemoryCatalog.from_directory(FIXTURE_DIRECTORY))
        if tool.tool_name == "search_catalog"
    )
    arguments = {"query": GOAL, "limit": 1}

    async def collect() -> list[ToolResult]:
        return [
            result
            async for result in search.stream(
                {"name": search.tool_name, "input": arguments, "toolUseId": "test"}, {}
            )
        ]

    assert asyncio.run(collect()) == [search.call(arguments, "test")]


@pytest.mark.parametrize("candidate_count", [2, 4])
def test_candidate_set_requires_exactly_three_candidates(candidate_count: int) -> None:
    evidence_id = "book:0000000000000000"
    candidate = candidate_set(evidence_id).candidates[0]

    with pytest.raises(ValidationError):
        ProjectCandidateSet(candidates=[candidate] * candidate_count)


def test_candidate_set_requires_unique_titles() -> None:
    evidence_id = "book:0000000000000000"
    candidate = candidate_set(evidence_id).candidates[0]

    with pytest.raises(ValidationError, match="titles must be unique"):
        ProjectCandidateSet(candidates=[candidate, candidate, candidate])
