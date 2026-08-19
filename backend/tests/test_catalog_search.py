from pathlib import Path

import pytest
from pydantic import ValidationError

from praxis.catalog import (
    CatalogKind,
    InMemoryCatalog,
    SearchCatalogRequest,
    search_catalog,
)
from praxis.domain import Book, Project

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


@pytest.fixture(scope="module")
def catalog() -> InMemoryCatalog:
    return InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)


def test_search_ranks_weighted_matches(catalog: InMemoryCatalog) -> None:
    results = search_catalog(catalog, SearchCatalogRequest(query="typescript notebook"))

    assert results
    assert isinstance(results[0].entry.item, Project)
    assert results[0].entry.item.name == "Circuit Notebook"
    assert results[0].score > 0


def test_search_filters_by_kind(catalog: InMemoryCatalog) -> None:
    results = search_catalog(
        catalog,
        SearchCatalogRequest(query="computing", kinds=frozenset({CatalogKind.BOOK})),
    )

    assert results
    assert all(isinstance(result.entry.item, Book) for result in results)


def test_search_honors_an_explicit_empty_kind_filter(catalog: InMemoryCatalog) -> None:
    request = SearchCatalogRequest(query="example", kinds=frozenset())

    assert not search_catalog(catalog, request)


def test_search_is_case_insensitive_and_bounded(catalog: InMemoryCatalog) -> None:
    results = search_catalog(catalog, SearchCatalogRequest(query="EXAMPLE", limit=3))

    assert len(results) == 3


def test_search_rejects_excessive_limits() -> None:
    with pytest.raises(ValidationError):
        SearchCatalogRequest(query="example", limit=21)


def test_search_rejects_blank_queries() -> None:
    with pytest.raises(ValidationError):
        SearchCatalogRequest(query="   ")


def test_search_returns_no_matches_for_unrelated_query(catalog: InMemoryCatalog) -> None:
    assert not search_catalog(catalog, SearchCatalogRequest(query="zyxwvutsrq"))
