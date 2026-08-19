from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from praxis.domain import Book, Byte, MuseumObject, Project

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"
MODEL_BY_FIXTURE = {
    "books": Book,
    "bytes": Byte,
    "museum": MuseumObject,
    "projects": Project,
}


@pytest.mark.parametrize(("fixture_name", "model"), MODEL_BY_FIXTURE.items())
def test_model_validates_fixture_records(
    fixture_name: str, model: type[Book | Byte | MuseumObject | Project]
) -> None:
    records = TypeAdapter(list[model]).validate_json(
        (FIXTURE_DIRECTORY / f"{fixture_name}.json").read_bytes()
    )

    assert len(records) == 2


def test_models_accept_source_aliases_and_expose_domain_names() -> None:
    project = Project.model_validate(
        {
            "name": "Example",
            "desc": "A project description.",
            "deployUrl": "https://example.invalid/app",
            "imageFocus": [0.5, 0.25],
        }
    )

    assert project.description == "A project description."
    assert project.deploy_url == "https://example.invalid/app"
    assert project.image_focus == [0.5, 0.25]


@pytest.mark.parametrize(
    "invalid_record",
    [
        {"title": "Example", "year": "2024"},
        {"title": "Example", "year": 2024, "unexpected": True},
    ],
)
def test_book_rejects_wrong_types_and_unknown_fields(
    invalid_record: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Book.model_validate(invalid_record)


def test_project_rejects_invalid_year_month() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(
            {"name": "Example", "desc": "A project description.", "date": "2024-13"}
        )
