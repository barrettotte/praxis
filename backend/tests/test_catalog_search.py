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


def test_search_filters_by_normalized_category(catalog: InMemoryCatalog) -> None:
    results = search_catalog(
        catalog,
        SearchCatalogRequest(
            query="software systems",
            categories=frozenset({" SOFTWARE ENGINEERING "}),
        ),
    )

    assert [result.entry.id for result in results] == ["book:13effac8435d4f50"]


def test_search_filters_by_normalized_language(catalog: InMemoryCatalog) -> None:
    book_results = search_catalog(
        catalog,
        SearchCatalogRequest(query="retro", languages=frozenset({"ENGLISH"})),
    )
    project_results = search_catalog(
        catalog,
        SearchCatalogRequest(query="notebook", languages=frozenset({"TypeScript"})),
    )

    assert [result.entry.id for result in book_results] == ["book:0f1a93bdfcbe1ab6"]
    assert [result.entry.id for result in project_results] == ["project:caf5bb80f7ceade5"]


def test_search_filters_by_inclusive_date_range(catalog: InMemoryCatalog) -> None:
    included = search_catalog(
        catalog,
        SearchCatalogRequest(query="notebook", date_from="2024-01", date_to="2024-12"),
    )
    excluded = search_catalog(
        catalog,
        SearchCatalogRequest(query="notebook", date_to="2023-12"),
    )

    assert [result.entry.id for result in included] == ["project:caf5bb80f7ceade5"]
    assert not excluded


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


def test_search_rejects_an_inverted_date_range() -> None:
    with pytest.raises(ValidationError, match="date_from"):
        SearchCatalogRequest(query="example", date_from="2025", date_to="2024")


def test_search_rejects_more_than_eight_searchable_tokens() -> None:
    with pytest.raises(ValidationError, match="at most 8"):
        SearchCatalogRequest(query="one two three four five six seven eight nine")


def test_search_stops_at_the_evaluated_record_budget() -> None:
    catalog = InMemoryCatalog(
        books=tuple(
            Book(title="Needle" if index == 1_500 else f"Book {index}", year=2024)
            for index in range(1_501)
        ),
        projects=(),
        bytes=(),
        museum_objects=(),
    )

    assert not search_catalog(catalog, SearchCatalogRequest(query="needle"))


def test_search_returns_no_matches_for_unrelated_query(catalog: InMemoryCatalog) -> None:
    assert not search_catalog(catalog, SearchCatalogRequest(query="zyxwvutsrq"))
