import json
from typing import cast
from unittest.mock import MagicMock

from strands import Agent
from strands.hooks import AfterToolCallEvent
from strands.types.tools import ToolResult

from praxis.agent.evidence import CatalogEvidenceLedger, read_evidence_state


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
            "content": [{"text": json.dumps(payload)}],
        },
    )
    return AfterToolCallEvent(
        agent=cast("Agent", MagicMock()),
        selected_tool=None,
        tool_use={"name": name, "input": {}, "toolUseId": f"{name}-call"},
        invocation_state=state,
        result=result,
    )


def book(evidence_id: str, title: str, *, scored: bool = False) -> dict[str, object]:
    record: dict[str, object] = {
        "evidence_id": evidence_id,
        "kind": "book",
        "title": title,
        "year": 2025,
        "tags": [],
    }
    if scored:
        record["score"] = 10
    return record


def test_evidence_ledger_collects_ids_from_catalog_results() -> None:
    ledger = CatalogEvidenceLedger()
    invocation_state: dict[str, object] = {}
    search = result_event(
        "search_catalog",
        {"results": [book("book:0000000000000001", "Compiler Design", scored=True)]},
        invocation_state,
    )
    scores = result_event(
        "score_project_candidates",
        {
            "scores": [
                {
                    "candidate_id": "compiler",
                    "history_overlap_score": 5,
                    "evidence_ids": ["project:0000000000000002"],
                }
            ]
        },
        invocation_state,
    )

    ledger.after_tool_call(search)
    ledger.after_tool_call(scores)

    state = read_evidence_state(invocation_state)
    assert state.evidence_ids == frozenset({"book:0000000000000001", "project:0000000000000002"})
    assert state.ordered_evidence_ids == (
        "book:0000000000000001",
        "project:0000000000000002",
    )
    assert not state.conflicting_ids


def test_evidence_ledger_accepts_consistent_search_and_lookup_facts() -> None:
    ledger = CatalogEvidenceLedger()
    invocation_state: dict[str, object] = {}
    evidence_id = "book:0000000000000001"

    ledger.after_tool_call(
        result_event(
            "search_catalog",
            {"results": [book(evidence_id, "Compiler Design", scored=True)]},
            invocation_state,
        )
    )
    lookup = result_event(
        "get_catalog_item",
        {"item": book(evidence_id, "Compiler Design")},
        invocation_state,
    )
    ledger.after_tool_call(lookup)

    assert lookup.result["status"] == "success"
    state = read_evidence_state(invocation_state)
    assert state.ordered_evidence_ids == (evidence_id,)
    assert not state.conflicting_ids


def test_evidence_ledger_rejects_conflicting_facts_for_one_id() -> None:
    ledger = CatalogEvidenceLedger()
    invocation_state: dict[str, object] = {}
    evidence_id = "book:0000000000000001"

    ledger.after_tool_call(
        result_event(
            "search_catalog",
            {"results": [book(evidence_id, "Compiler Design", scored=True)]},
            invocation_state,
        )
    )
    conflicting = result_event(
        "get_catalog_item",
        {"item": book(evidence_id, "Different Title")},
        invocation_state,
    )
    ledger.after_tool_call(conflicting)

    assert conflicting.result == {
        "toolUseId": "get_catalog_item-call",
        "status": "error",
        "content": [{"text": f"Conflicting catalog facts detected for evidence: {evidence_id}"}],
    }
    assert read_evidence_state(invocation_state).conflicting_ids == frozenset({evidence_id})


def test_evidence_ledger_preserves_empty_search_state() -> None:
    invocation_state: dict[str, object] = {}
    event = result_event("search_catalog", {"results": []}, invocation_state)

    CatalogEvidenceLedger().after_tool_call(event)

    assert event.result["status"] == "success"
    assert not read_evidence_state(invocation_state).evidence_ids
