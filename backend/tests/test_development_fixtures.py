import json
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest

type JsonObject = dict[str, JsonValue]
type JsonValue = bool | int | float | str | list[JsonValue] | JsonObject | None

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"
EXPECTED_REQUIRED_KEYS = {
    "books": {"author", "category", "title", "year"},
    "bytes": {"category", "date", "name", "url"},
    "museum": {
        "category",
        "description",
        "id",
        "image",
        "manufacturer",
        "name",
        "year",
    },
    "projects": {"date", "desc", "languages", "name"},
}


def load_fixture(name: str) -> list[JsonObject]:
    raw_records = cast(
        "JsonValue",
        json.loads((FIXTURE_DIRECTORY / f"{name}.json").read_text(encoding="utf-8")),
    )
    assert isinstance(raw_records, list)
    assert all(isinstance(record, dict) for record in raw_records)
    return cast("list[JsonObject]", raw_records)


def string_values(value: JsonValue) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested_value in value.values() for item in string_values(nested_value)]
    if isinstance(value, list):
        return [item for nested_value in value for item in string_values(nested_value)]
    return []


@pytest.mark.parametrize(("name", "required_keys"), EXPECTED_REQUIRED_KEYS.items())
def test_fixture_has_representative_records(name: str, required_keys: set[str]) -> None:
    records = load_fixture(name)

    assert len(records) == 2
    assert all(required_keys <= record.keys() for record in records)


def test_fixture_external_urls_use_reserved_domain() -> None:
    values = [
        value
        for name in EXPECTED_REQUIRED_KEYS
        for record in load_fixture(name)
        for value in string_values(record)
    ]
    external_urls = [value for value in values if value.startswith(("http://", "https://"))]

    assert external_urls
    assert all(urlsplit(url).hostname == "example.invalid" for url in external_urls)
