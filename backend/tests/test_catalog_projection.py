from pathlib import Path

from praxis.catalog import InMemoryCatalog, catalog_entry, project_evidence
from praxis.domain import Book

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


def test_evidence_projection_returns_only_agent_fields() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    projections = {entry.kind.value: project_evidence(entry) for entry in catalog.entries()}

    assert set(projections["book"]) == {
        "evidence_id",
        "kind",
        "title",
        "author",
        "year",
        "category",
        "tags",
    }
    assert set(projections["project"]) == {
        "evidence_id",
        "kind",
        "name",
        "description",
        "date",
        "languages",
    }
    assert set(projections["byte"]) == {
        "evidence_id",
        "kind",
        "name",
        "category",
        "date",
    }
    assert set(projections["museum"]) == {
        "evidence_id",
        "kind",
        "name",
        "manufacturer",
        "category",
        "description",
    }


def test_evidence_projection_excludes_internal_and_source_fields() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)

    for projection in (project_evidence(entry) for entry in catalog.entries()):
        assert (
            not {
                "deployUrl",
                "hidden",
                "image",
                "isbn10",
                "isbn13",
                "lccn",
                "model",
                "source",
                "url",
            }
            & projection.keys()
        )


def test_evidence_projection_omits_empty_optional_values() -> None:
    projection = project_evidence(
        catalog_entry(Book(title="Anonymous Systems Notes", author="", year=1980))
    )

    assert "author" not in projection
    assert "category" not in projection
