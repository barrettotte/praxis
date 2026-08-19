from pathlib import Path

import pytest
from pydantic import ValidationError

from praxis.catalog import (
    CatalogItemNotFoundError,
    GetCatalogItemRequest,
    InMemoryCatalog,
    get_catalog_item,
)

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


@pytest.fixture(scope="module")
def catalog() -> InMemoryCatalog:
    return InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)


def test_get_catalog_item_returns_entry_by_evidence_id(
    catalog: InMemoryCatalog,
) -> None:
    expected = next(catalog.entries())

    actual = get_catalog_item(catalog, GetCatalogItemRequest(id=expected.id))

    assert actual == expected


def test_get_catalog_item_reports_unknown_evidence_id(
    catalog: InMemoryCatalog,
) -> None:
    request = GetCatalogItemRequest(id="book:0000000000000000")

    with pytest.raises(CatalogItemNotFoundError, match=request.id):
        get_catalog_item(catalog, request)


@pytest.mark.parametrize("item_id", ["book:short", "unknown:0000000000000000"])
def test_get_catalog_item_rejects_malformed_evidence_id(item_id: str) -> None:
    with pytest.raises(ValidationError):
        GetCatalogItemRequest(id=item_id)
