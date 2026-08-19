from typing import cast

import pytest

from praxis.domain import (
    CandidateOutputValidationError,
    candidate_output_schema,
    validate_candidate_output,
)
from praxis.domain.candidate_validation import JsonValue

EVIDENCE_ID = "book:0000000000000000"


def candidate_payload() -> dict[str, JsonValue]:
    payload = {
        "candidates": [
            {
                "title": f"Candidate {number}",
                "summary": "Build a focused project.",
                "rationale": "It connects the requested goal to prior evidence.",
                "estimated_scope": "multi-week",
                "technologies": ["TypeScript"],
                "first_milestone": "Render one static notebook entry.",
                "evidence": [
                    {
                        "evidence_id": EVIDENCE_ID,
                        "connection": "The record demonstrates related experience.",
                    }
                ],
            }
            for number in range(1, 4)
        ]
    }
    return cast("dict[str, JsonValue]", payload)


def candidate_records(payload: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    return cast("list[dict[str, JsonValue]]", payload["candidates"])


def test_candidate_output_schema_declares_draft_2020_12() -> None:
    schema = candidate_output_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False


def test_validate_candidate_output_accepts_valid_payload() -> None:
    validated = validate_candidate_output(candidate_payload())

    assert len(validated.candidates) == 3


def test_validate_candidate_output_rejects_schema_violation() -> None:
    payload = candidate_payload()
    candidate_records(payload)[0].pop("evidence")

    with pytest.raises(CandidateOutputValidationError, match=r"JSON Schema.*evidence"):
        validate_candidate_output(payload)


def test_validate_candidate_output_rejects_additional_properties() -> None:
    payload = candidate_payload()
    candidate_records(payload)[0]["internal_notes"] = "must not escape"

    with pytest.raises(CandidateOutputValidationError, match="Additional properties"):
        validate_candidate_output(payload)


def test_validate_candidate_output_applies_semantic_constraints() -> None:
    payload = candidate_payload()
    for candidate in candidate_records(payload):
        candidate["title"] = "Repeated title"

    with pytest.raises(CandidateOutputValidationError, match="semantic validation"):
        validate_candidate_output(payload)
