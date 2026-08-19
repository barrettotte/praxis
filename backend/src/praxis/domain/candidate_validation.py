"""JSON Schema validation for generated project candidates."""

from copy import deepcopy
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.protocols import Validator
from pydantic import ValidationError as PydanticValidationError

from praxis.domain.candidates import ProjectCandidateSet

JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
CANDIDATE_OUTPUT_SCHEMA = cast(
    "dict[str, JsonValue]",
    ProjectCandidateSet.model_json_schema(mode="validation"),
)
CANDIDATE_OUTPUT_SCHEMA["$schema"] = JSON_SCHEMA_DRAFT
Draft202012Validator.check_schema(CANDIDATE_OUTPUT_SCHEMA)
CANDIDATE_OUTPUT_VALIDATOR: Validator = Draft202012Validator(CANDIDATE_OUTPUT_SCHEMA)


class CandidateOutputValidationError(ValueError):
    """Raised when generated candidate output violates its contract."""


def candidate_output_schema() -> dict[str, JsonValue]:
    """Return a defensive copy of the candidate JSON Schema contract."""
    return deepcopy(CANDIDATE_OUTPUT_SCHEMA)


def validate_candidate_output(payload: JsonValue) -> ProjectCandidateSet:
    """Validate raw model output against JSON Schema and semantic constraints."""
    try:
        CANDIDATE_OUTPUT_VALIDATOR.validate(payload)
    except JsonSchemaValidationError as error:
        message = (
            f"Candidate output failed JSON Schema validation at {error.json_path}: {error.message}"
        )
        raise CandidateOutputValidationError(message) from error

    try:
        return ProjectCandidateSet.model_validate(payload)
    except PydanticValidationError as error:
        message = "Candidate output failed semantic validation"
        raise CandidateOutputValidationError(message) from error
