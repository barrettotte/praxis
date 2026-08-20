from pathlib import Path

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
from praxis.functions.catalog import CatalogRepository, handle_catalog_request

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


class LocalCatalogRepository(CatalogRepository):
    def __init__(self, catalog: InMemoryCatalog) -> None:
        self._catalog = catalog

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        return search_catalog(self._catalog, request)

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        return get_catalog_item(self._catalog, request)


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
