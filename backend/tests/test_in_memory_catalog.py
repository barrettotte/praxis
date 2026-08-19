from pathlib import Path

import pytest

from praxis.catalog import CatalogLoadError, InMemoryCatalog
from praxis.domain import Book, Byte, MuseumObject, Project

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


def test_catalog_loads_all_fixture_collections() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)

    assert len(catalog) == 8
    assert len(catalog.books) == 2
    assert len(catalog.projects) == 2
    assert len(catalog.bytes) == 2
    assert len(catalog.museum_objects) == 2


def test_catalog_preserves_typed_collection_order() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)

    assert [type(item) for item in catalog] == [
        Book,
        Book,
        Project,
        Project,
        Byte,
        Byte,
        MuseumObject,
        MuseumObject,
    ]


def test_catalog_assigns_deterministic_unique_evidence_ids() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)

    first_ids = [entry.id for entry in catalog.entries()]
    second_ids = [entry.id for entry in catalog.entries()]

    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))


def test_book_evidence_ids_do_not_rely_on_isbn_alone() -> None:
    catalog = InMemoryCatalog(
        books=(
            Book(title="Volume One", year=2024, isbn_13="0000000000000"),
            Book(title="Volume Two", year=2024, isbn_13="0000000000000"),
        ),
        projects=(),
        bytes=(),
        museum_objects=(),
    )

    assert len({entry.id for entry in catalog.entries()}) == 2


def test_catalog_reports_the_collection_that_failed_to_load(tmp_path: Path) -> None:
    with pytest.raises(CatalogLoadError, match=r"books\.json"):
        InMemoryCatalog.from_directory(tmp_path)
