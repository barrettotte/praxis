from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from praxis.catalog import (
    CatalogEntry,
    CatalogSearchResult,
    GetCatalogItemRequest,
    InMemoryCatalog,
    SearchCatalogRequest,
    get_catalog_item,
    search_catalog,
)
from praxis.functions.catalog import (
    CatalogRepository,
    CatalogToolError,
    handle_catalog_invocation,
    handle_catalog_request,
)

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


class LocalCatalogRepository(CatalogRepository):
    def __init__(self, catalog: InMemoryCatalog) -> None:
        self._catalog = catalog

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        return search_catalog(self._catalog, request)

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        return get_catalog_item(self._catalog, request)

    def project_entries(self) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self._catalog.entries() if entry.kind.value == "project")


@dataclass(frozen=True)
class GatewayClientContext:
    custom: dict[str, Any]


@dataclass(frozen=True)
class GatewayContext:
    client_context: GatewayClientContext
    remaining_time_ms: int = 15_000

    def get_remaining_time_in_millis(self) -> int:
        return self.remaining_time_ms


def gateway_context(tool_name: object, *, remaining_time_ms: int = 15_000) -> GatewayContext:
    return GatewayContext(
        client_context=GatewayClientContext(custom={"bedrockAgentCoreToolName": tool_name}),
        remaining_time_ms=remaining_time_ms,
    )


@pytest.fixture
def repository() -> LocalCatalogRepository:
    return LocalCatalogRepository(InMemoryCatalog.from_directory(FIXTURE_DIRECTORY))


def test_catalog_lambda_searches_with_strict_filters(
    repository: LocalCatalogRepository,
) -> None:
    response = handle_catalog_request(
        {
            "operation": "search_catalog",
            "arguments": {
                "query": "notebook",
                "languages": ["TypeScript"],
                "date_from": "2024-01",
                "limit": 3,
            },
        },
        repository,
    )

    assert response == {
        "operation": "search_catalog",
        "results": [
            {
                "score": 20,
                "evidence_id": "project:caf5bb80f7ceade5",
                "kind": "project",
                "name": "Circuit Notebook",
                "description": "A browser-based notebook for documenting electronics experiments.",
                "date": "2024-09",
                "languages": ["typescript", "css"],
            }
        ],
    }


def test_catalog_lambda_gets_only_projected_fields(repository: LocalCatalogRepository) -> None:
    response = handle_catalog_request(
        {
            "operation": "get_catalog_item",
            "arguments": {"id": "book:0f1a93bdfcbe1ab6"},
        },
        repository,
    )

    item = response["item"]
    assert isinstance(item, dict)
    assert item["evidence_id"] == "book:0f1a93bdfcbe1ab6"
    assert not {"isbn10", "lccn", "payload", "source"} & item.keys()


def test_catalog_lambda_accepts_agentcore_gateway_events(
    repository: LocalCatalogRepository,
) -> None:
    response = handle_catalog_invocation(
        {"query": "notebook", "languages": ["TypeScript"], "limit": 1},
        gateway_context("praxis-dev-catalog___search_catalog"),
        repository,
    )

    assert "operation" not in response
    assert response["results"] == [
        {
            "score": 20,
            "evidence_id": "project:caf5bb80f7ceade5",
            "kind": "project",
            "name": "Circuit Notebook",
            "description": "A browser-based notebook for documenting electronics experiments.",
            "date": "2024-09",
            "languages": ["typescript", "css"],
        }
    ]


def test_catalog_lambda_summarizes_project_history(
    repository: LocalCatalogRepository,
) -> None:
    response = handle_catalog_invocation(
        {
            "description": "A browser notebook for electronics experiments",
            "languages": ["TypeScript"],
            "limit": 1,
        },
        gateway_context("praxis-dev-catalog___summarize_experience"),
        repository,
    )

    matches = response["matches"]
    assert isinstance(matches, list)
    assert matches == [
        {
            "evidence_id": "project:caf5bb80f7ceade5",
            "name": "Circuit Notebook",
            "date": "2024-09",
            "matched_terms": ["browser", "electronics", "notebook"],
            "shared_languages": ["typescript"],
            "history_overlap_score": 8,
        }
    ]


def test_catalog_lambda_scores_candidates_against_project_history(
    repository: LocalCatalogRepository,
) -> None:
    payload: dict[str, object] = {
        "candidates": [
            {
                "candidate_id": "notebook",
                "description": "A browser notebook for electronics experiments",
                "languages": ["TypeScript"],
            },
            {
                "candidate_id": "unrelated",
                "description": "zyxwvutsrq",
                "languages": [],
            },
        ]
    }
    response = handle_catalog_invocation(
        payload,
        gateway_context("praxis-dev-catalog___score_project_candidates"),
        repository,
    )

    scores = response["scores"]
    assert isinstance(scores, list)
    assert scores[0] == {
        "candidate_id": "notebook",
        "history_overlap_score": 8,
        "evidence_ids": ["project:caf5bb80f7ceade5"],
    }
    assert scores[1] == {
        "candidate_id": "unrelated",
        "history_overlap_score": 0,
        "evidence_ids": [],
    }


@pytest.mark.parametrize(
    "tool_name",
    [
        "praxis-dev-catalog___delete_catalog",
        "missing-delimiter",
        42,
    ],
)
def test_catalog_lambda_rejects_unsupported_gateway_tool_context(
    repository: LocalCatalogRepository, tool_name: object
) -> None:
    with pytest.raises(CatalogToolError) as raised:
        handle_catalog_invocation({}, gateway_context(tool_name), repository)

    assert raised.value.as_dict() == {
        "code": "INVALID_ARGUMENTS",
        "message": "Catalog tool arguments are invalid.",
        "retryable": False,
    }


def test_catalog_lambda_returns_a_safe_timeout_before_hard_termination(
    repository: LocalCatalogRepository,
) -> None:
    with pytest.raises(CatalogToolError) as raised:
        handle_catalog_invocation(
            {"query": "compiler"},
            gateway_context("praxis-dev-catalog___search_catalog", remaining_time_ms=5_999),
            repository,
        )

    assert raised.value.as_dict() == {
        "code": "TIMEOUT",
        "message": "Catalog tool did not have enough time to complete.",
        "retryable": True,
    }


def test_catalog_lambda_does_not_leak_invalid_argument_details(
    repository: LocalCatalogRepository,
) -> None:
    with pytest.raises(CatalogToolError) as raised:
        handle_catalog_invocation(
            {"query": "compiler", "private_field": "must-not-leak"},
            gateway_context("praxis-dev-catalog___search_catalog"),
            repository,
        )

    assert "must-not-leak" not in str(raised.value)
    assert raised.value.as_dict()["code"] == "INVALID_ARGUMENTS"


def test_catalog_lambda_returns_a_safe_not_found_error(
    repository: LocalCatalogRepository,
) -> None:
    with pytest.raises(CatalogToolError) as raised:
        handle_catalog_invocation(
            {"id": "book:0000000000000000"},
            gateway_context("praxis-dev-catalog___get_catalog_item"),
            repository,
        )

    assert raised.value.as_dict() == {
        "code": "NOT_FOUND",
        "message": "Catalog item was not found.",
        "retryable": False,
    }


@pytest.mark.parametrize(
    "event",
    [
        {"operation": "delete_catalog", "arguments": {}},
        {"operation": "search_catalog", "arguments": {"query": "example", "limit": 21}},
        {"operation": "search_catalog", "arguments": {"query": "example"}, "extra": True},
    ],
)
def test_catalog_lambda_rejects_invalid_invocations(
    repository: LocalCatalogRepository, event: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        handle_catalog_request(event, repository)
