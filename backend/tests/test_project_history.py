from pathlib import Path

import pytest
from pydantic import ValidationError

from praxis.catalog import (
    CompareProjectHistoryRequest,
    InMemoryCatalog,
    compare_project_history,
)

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


@pytest.fixture(scope="module")
def catalog() -> InMemoryCatalog:
    return InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)


def test_compare_project_history_reports_factual_overlap(
    catalog: InMemoryCatalog,
) -> None:
    request = CompareProjectHistoryRequest(
        description="A browser notebook for electronics experiments",
        languages=frozenset({"TypeScript"}),
    )

    matches = compare_project_history(catalog, request)

    assert matches
    assert matches[0].project.name == "Circuit Notebook"
    assert matches[0].shared_languages == ("typescript",)
    assert {"browser", "electronics", "notebook"} <= set(matches[0].matched_terms)


def test_compare_project_history_is_bounded(catalog: InMemoryCatalog) -> None:
    request = CompareProjectHistoryRequest(description="catalog notebook", limit=1)

    assert len(compare_project_history(catalog, request)) == 1


def test_compare_project_history_returns_no_unrelated_projects(
    catalog: InMemoryCatalog,
) -> None:
    request = CompareProjectHistoryRequest(description="zyxwvutsrq")

    assert not compare_project_history(catalog, request)


@pytest.mark.parametrize(
    "values",
    [
        {"description": "   "},
        {"description": "example", "limit": 11},
    ],
)
def test_compare_project_history_rejects_invalid_requests(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CompareProjectHistoryRequest.model_validate(values)
