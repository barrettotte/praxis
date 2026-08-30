from typing import cast
from unittest.mock import MagicMock

import pytest
from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.types.tools import ToolResult

from praxis.agent.budget import (
    CatalogResultBudget,
    ToolCallBudget,
    ToolCallBudgetError,
    seed_catalog_budgets,
)


def tool_event(name: str, state: dict[str, object]) -> BeforeToolCallEvent:
    return BeforeToolCallEvent(
        agent=cast("Agent", MagicMock()),
        selected_tool=None,
        tool_use={"name": name, "input": {}, "toolUseId": f"{name}-call"},
        invocation_state=state,
    )


def result_event(
    name: str,
    payload: object,
    state: dict[str, object],
) -> AfterToolCallEvent:
    result = cast(
        "ToolResult",
        {
            "toolUseId": f"{name}-call",
            "status": "success",
            "content": [{"json": payload}],
            "structuredContent": payload,
        },
    )
    return AfterToolCallEvent(
        agent=cast("Agent", MagicMock()),
        selected_tool=None,
        tool_use={"name": name, "input": {}, "toolUseId": f"{name}-call"},
        invocation_state=state,
        result=result,
    )


def book(evidence_id: str, *, scored: bool = False) -> dict[str, object]:
    record: dict[str, object] = {
        "evidence_id": evidence_id,
        "kind": "book",
        "title": "Compiler Design",
        "year": 2025,
        "tags": [],
    }
    if scored:
        record["score"] = 10
    return record


def test_tool_call_budget_stops_before_executing_beyond_limit() -> None:
    budget = ToolCallBudget(maximum_calls=2, tool_names=frozenset({"search_catalog"}))
    invocation_state: dict[str, object] = {}

    budget.before_tool_call(tool_event("search_catalog", invocation_state))
    budget.before_tool_call(tool_event("search_catalog", invocation_state))

    with pytest.raises(ToolCallBudgetError, match="maximum 2 calls"):
        budget.before_tool_call(tool_event("search_catalog", invocation_state))


def test_tool_call_budget_excludes_internal_structured_output_tool() -> None:
    budget = ToolCallBudget(maximum_calls=1, tool_names=frozenset({"search_catalog"}))
    invocation_state: dict[str, object] = {}

    budget.before_tool_call(tool_event("ProjectCandidateSet", invocation_state))
    budget.before_tool_call(tool_event("search_catalog", invocation_state))


def test_tool_call_budget_is_scoped_to_one_invocation() -> None:
    budget = ToolCallBudget(maximum_calls=1, tool_names=frozenset({"search_catalog"}))

    budget.before_tool_call(tool_event("search_catalog", {}))
    budget.before_tool_call(tool_event("search_catalog", {}))


def test_tool_call_budget_requires_a_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        ToolCallBudget(maximum_calls=0, tool_names=frozenset({"search_catalog"}))


def test_seeded_catalog_call_counts_against_model_budget() -> None:
    invocation_state: dict[str, object] = {}
    seed_catalog_budgets(invocation_state, tool_calls=1, result_count=3)
    budget = ToolCallBudget(maximum_calls=1, tool_names=frozenset({"search_catalog"}))

    with pytest.raises(ToolCallBudgetError, match="maximum 1 calls"):
        budget.before_tool_call(tool_event("search_catalog", invocation_state))


@pytest.mark.parametrize(
    ("tool_name", "payload", "result_count"),
    [
        (
            "search_catalog",
            {
                "results": [
                    book("book:0000000000000001", scored=True),
                    book("book:0000000000000002", scored=True),
                ]
            },
            2,
        ),
        ("get_catalog_item", {"item": book("book:0000000000000001")}, 1),
        (
            "summarize_experience",
            {
                "matches": [
                    {
                        "evidence_id": f"project:{number:016x}",
                        "name": f"Project {number}",
                        "matched_terms": ["compiler"],
                        "shared_languages": ["python"],
                        "history_overlap_score": 5,
                    }
                    for number in range(1, 3)
                ]
            },
            2,
        ),
        (
            "score_project_candidates",
            {
                "scores": [
                    {
                        "candidate_id": "compiler",
                        "history_overlap_score": 5,
                        "evidence_ids": [
                            "project:0000000000000001",
                            "project:0000000000000002",
                        ],
                    }
                ]
            },
            2,
        ),
    ],
)
def test_catalog_result_budget_counts_each_strict_tool_response(
    tool_name: str,
    payload: object,
    result_count: int,
) -> None:
    budget = CatalogResultBudget(maximum_results=result_count)
    invocation_state: dict[str, object] = {}
    accepted = result_event(tool_name, payload, invocation_state)

    budget.after_tool_call(accepted)
    rejected = result_event(
        "get_catalog_item",
        {"item": book("book:0000000000000003")},
        invocation_state,
    )
    budget.after_tool_call(rejected)

    assert accepted.result["status"] == "success"
    assert rejected.result == {
        "toolUseId": "get_catalog_item-call",
        "status": "error",
        "content": [
            {
                "text": (
                    f"Catalog result budget exhausted: maximum {result_count} records "
                    "per invocation"
                )
            }
        ],
    }


def test_catalog_result_budget_rejects_malformed_structured_content() -> None:
    budget = CatalogResultBudget(maximum_results=20)
    event = result_event("search_catalog", {"results": [{"kind": "book"}]}, {})

    budget.after_tool_call(event)

    assert event.result["status"] == "error"
    assert event.result["content"] == [
        {"text": "Catalog tool returned an invalid structured result"}
    ]


def test_catalog_result_budget_ignores_non_catalog_tools() -> None:
    budget = CatalogResultBudget(maximum_results=1)
    event = result_event("ProjectCandidateSet", {"candidates": []}, {})

    budget.after_tool_call(event)

    assert event.result["status"] == "success"


def test_catalog_result_budget_requires_a_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        CatalogResultBudget(maximum_results=0)
