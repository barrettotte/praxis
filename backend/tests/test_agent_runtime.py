"""Tests for the AgentCore Runtime entry point."""

from typing import Protocol, cast

import pytest

from praxis.agent.gateway import GatewayAgentRun
from praxis.agent.runtime import RuntimeRequestError, app, invoke_runtime
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet


class RuntimeRoute(Protocol):
    path: str
    methods: set[str] | None


class RoutedRuntimeApplication(Protocol):
    routes: list[RuntimeRoute]


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
                        generated_connection="The evidence supports this learning path.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def test_runtime_app_exposes_agentcore_http_contract() -> None:
    routes = cast("RoutedRuntimeApplication", app).routes

    assert any(
        route.path == "/ping" and route.methods is not None and "GET" in route.methods
        for route in routes
    )
    assert any(
        route.path == "/invocations" and route.methods is not None and "POST" in route.methods
        for route in routes
    )


@pytest.mark.parametrize("payload", [{}, {"prompt": ""}, {"prompt": "  "}, {"prompt": 7}])
def test_invoke_runtime_rejects_invalid_prompts(payload: dict[str, object]) -> None:
    with pytest.raises(RuntimeRequestError, match="prompt must be a non-empty string"):
        invoke_runtime(payload, lambda _: GatewayAgentRun(candidate_set(), ()))


def test_invoke_runtime_returns_buffered_candidates_and_tool_metrics() -> None:
    observed_prompts: list[str] = []

    def invoke_agent(prompt: str) -> GatewayAgentRun:
        observed_prompts.append(prompt)
        return GatewayAgentRun(
            candidates=candidate_set(),
            tool_calls=(("get_catalog_item", 1), ("search_catalog", 2)),
        )

    response = invoke_runtime({"prompt": "  Recommend a compiler project  "}, invoke_agent)

    assert observed_prompts == ["Recommend a compiler project"]
    candidates = response["candidates"]
    assert isinstance(candidates, list)
    assert len(cast("list[object]", candidates)) == 3
    assert response["tool_calls"] == [
        {"name": "get_catalog_item", "count": 1},
        {"name": "search_catalog", "count": 2},
    ]
