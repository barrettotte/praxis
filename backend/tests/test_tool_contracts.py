from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from praxis.tools import (
    gateway_tool_definitions,
    gateway_tool_definitions_json,
    strict_tool_json_schemas,
    validate_tool_input,
    validate_tool_output,
)

GATEWAY_SCHEMA_ARTIFACT = Path(__file__).parents[2] / "infra" / "schemas" / "agentcore-tools.json"


def test_all_planned_tools_have_strict_input_and_output_schemas() -> None:
    schemas = strict_tool_json_schemas()

    assert set(schemas) == {
        "search_catalog",
        "get_catalog_item",
        "summarize_experience",
        "score_project_candidates",
    }
    for tool_schemas in schemas.values():
        for schema in tool_schemas.values():
            Draft202012Validator.check_schema(schema)
            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["additionalProperties"] is False


def test_gateway_definitions_use_only_the_agentcore_schema_subset() -> None:
    definitions = gateway_tool_definitions()

    assert [definition.name for definition in definitions] == [
        "search_catalog",
        "get_catalog_item",
        "summarize_experience",
        "score_project_candidates",
    ]
    dumped = [definition.model_dump(by_alias=True, exclude_none=True) for definition in definitions]
    unsupported_keys = {
        "$defs",
        "$ref",
        "$schema",
        "additionalProperties",
        "anyOf",
        "const",
        "enum",
        "maximum",
        "minimum",
        "maxItems",
        "minItems",
        "pattern",
    }

    def assert_supported(value: object) -> None:
        if isinstance(value, dict):
            mapping = cast("dict[object, object]", value)
            assert not ({str(key) for key in mapping} & unsupported_keys)
            for nested in mapping.values():
                assert_supported(nested)
        elif isinstance(value, list):
            for nested in cast("list[object]", value):
                assert_supported(nested)

    assert_supported(dumped)


def test_open_tofu_gateway_schema_artifact_matches_contracts() -> None:
    assert GATEWAY_SCHEMA_ARTIFACT.read_text() == gateway_tool_definitions_json()


def test_tool_descriptions_are_compact_and_distinguish_usage() -> None:
    descriptions = {
        definition.name: definition.description for definition in gateway_tool_definitions()
    }

    assert descriptions == {
        "search_catalog": (
            "Find relevant books, projects, technical artifacts, and museum objects using text "
            "and exact filters."
        ),
        "get_catalog_item": (
            "Retrieve one evidence record using a stable evidence ID returned by another "
            "catalog tool."
        ),
        "summarize_experience": (
            "Return prior projects sharing terms or programming languages with one proposed "
            "project."
        ),
        "score_project_candidates": (
            "Score term and language overlap for up to three proposals; return three supporting "
            "evidence IDs each."
        ),
    }
    assert all(len(description) <= 120 for description in descriptions.values())
    assert all(
        description.endswith(".") and description.count(".") == 1
        for description in descriptions.values()
    )


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("search_catalog", {"query": "compiler", "limit": 21}),
        ("get_catalog_item", {"id": "not-an-evidence-id"}),
        ("summarize_experience", {"description": "compiler", "extra": True}),
        (
            "score_project_candidates",
            {
                "candidates": [
                    {"candidate_id": "same", "description": "first"},
                    {"candidate_id": "same", "description": "second"},
                ]
            },
        ),
    ],
)
def test_strict_inputs_reject_invalid_or_extra_values(
    tool_name: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        validate_tool_input(tool_name, payload)  # pyright: ignore[reportArgumentType]


def test_search_input_accepts_json_arrays_for_exact_filters() -> None:
    validated = validate_tool_input(
        "search_catalog",
        {
            "query": "compiler",
            "kinds": ["book"],
            "languages": ["English"],
            "limit": 3,
        },
    )

    assert validated.model_dump(mode="json") == {
        "query": "compiler",
        "kinds": ["book"],
        "categories": None,
        "languages": ["english"],
        "date_from": None,
        "date_to": None,
        "limit": 3,
    }


def test_search_output_accepts_projected_evidence_and_rejects_metadata() -> None:
    output: dict[str, object] = {
        "results": [
            {
                "score": 34,
                "evidence_id": "book:0f5ba253568e4836",
                "kind": "book",
                "title": "LLVM Code Generation A Deep Dive Into Compiler Backend Development",
                "author": "Quentin Colombet",
                "year": 2025,
                "category": "Compilers, Interpreters, and Operating Systems",
                "tags": [],
            }
        ]
    }

    validated = validate_tool_output("search_catalog", output)
    assert validated.model_dump(mode="json") == output

    leaked = deepcopy(output)
    results = leaked["results"]
    assert isinstance(results, list)
    first = cast("list[object]", results)[0]
    assert isinstance(first, dict)
    cast("dict[str, object]", first)["payload"] = {"internal": True}
    with pytest.raises(ValidationError):
        validate_tool_output("search_catalog", leaked)
