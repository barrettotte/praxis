"""Canonical strict runtime contracts and AgentCore-compatible tool schemas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal, Self, cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from praxis.catalog import GetCatalogItemRequest, SearchCatalogRequest
from praxis.domain.candidate_validation import JSON_SCHEMA_DRAFT, JsonValue

type EvidenceId = Annotated[
    str,
    Field(pattern=r"^(book|byte|museum|project):[0-9a-f]{16}$"),
]
type NonEmptyText = Annotated[str, Field(min_length=1, max_length=4_000)]
type ShortLabel = Annotated[str, Field(min_length=1, max_length=200)]
type ToolName = Literal[
    "search_catalog",
    "get_catalog_item",
    "summarize_experience",
    "score_project_candidates",
]
type SchemaType = Literal["string", "number", "object", "array", "boolean", "integer"]


class ToolModel(BaseModel):
    """Forbid undeclared fields and coercion at every tool boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class BookEvidence(ToolModel):
    """Agent-safe projection of one book record."""

    evidence_id: EvidenceId
    kind: Literal["book"]
    title: NonEmptyText
    author: NonEmptyText | None = None
    year: Annotated[int, Field(ge=0)]
    category: ShortLabel | None = None
    tags: Annotated[list[ShortLabel], Field(max_length=50)]


class ProjectEvidence(ToolModel):
    """Agent-safe projection of one historical project."""

    evidence_id: EvidenceId
    kind: Literal["project"]
    name: ShortLabel
    description: NonEmptyText
    date: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] | None = None
    languages: Annotated[list[ShortLabel], Field(max_length=50)]


class ByteEvidence(ToolModel):
    """Agent-safe projection of one technical artifact."""

    evidence_id: EvidenceId
    kind: Literal["byte"]
    name: ShortLabel
    category: ShortLabel
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class MuseumEvidence(ToolModel):
    """Agent-safe projection of one computing-museum object."""

    evidence_id: EvidenceId
    kind: Literal["museum"]
    name: ShortLabel
    manufacturer: ShortLabel
    year: Annotated[int, Field(ge=0)] | None = None
    category: ShortLabel
    description: NonEmptyText


type Evidence = Annotated[
    BookEvidence | ProjectEvidence | ByteEvidence | MuseumEvidence,
    Field(discriminator="kind"),
]


class BookSearchResult(BookEvidence):
    """Scored book search result."""

    score: Annotated[int, Field(ge=1)]


class ProjectSearchResult(ProjectEvidence):
    """Scored project search result."""

    score: Annotated[int, Field(ge=1)]


class ByteSearchResult(ByteEvidence):
    """Scored technical-artifact search result."""

    score: Annotated[int, Field(ge=1)]


class MuseumSearchResult(MuseumEvidence):
    """Scored museum-object search result."""

    score: Annotated[int, Field(ge=1)]


type SearchResult = Annotated[
    BookSearchResult | ProjectSearchResult | ByteSearchResult | MuseumSearchResult,
    Field(discriminator="kind"),
]


class SearchCatalogOutput(ToolModel):
    """Bounded catalog search response."""

    results: Annotated[list[SearchResult], Field(max_length=20)]


class GetCatalogItemOutput(ToolModel):
    """One projected catalog record."""

    item: Evidence


class SummarizeExperienceInput(ToolModel):
    """Candidate characteristics used to find factual prior-project overlap."""

    description: Annotated[str, Field(min_length=1, max_length=2_000)]
    languages: Annotated[list[ShortLabel], Field(max_length=10)] = Field(default_factory=list)
    limit: Annotated[int, Field(ge=1, le=10)] = 5


class ExperienceMatch(ToolModel):
    """Factual overlap with one historical project."""

    evidence_id: EvidenceId
    name: ShortLabel
    date: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] | None = None
    matched_terms: Annotated[list[ShortLabel], Field(max_length=50)]
    shared_languages: Annotated[list[ShortLabel], Field(max_length=10)]
    history_overlap_score: Annotated[int, Field(ge=1)]


class SummarizeExperienceOutput(ToolModel):
    """Bounded prior-project evidence relevant to one proposal."""

    matches: Annotated[list[ExperienceMatch], Field(max_length=10)]


class CandidateToScore(ToolModel):
    """One proposed project evaluated against factual project history."""

    candidate_id: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
    ]
    description: Annotated[str, Field(min_length=1, max_length=2_000)]
    languages: Annotated[list[ShortLabel], Field(max_length=10)] = Field(default_factory=list)


class ScoreProjectCandidatesInput(ToolModel):
    """One to three proposals to compare with historical project evidence."""

    candidates: Annotated[list[CandidateToScore], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def require_unique_candidate_ids(self) -> Self:
        """Keep score results unambiguous."""
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate_id values must be unique")
        return self


class CandidateHistoryScore(ToolModel):
    """Deterministic history-overlap score for one proposal."""

    candidate_id: Annotated[str, Field(min_length=1, max_length=64)]
    history_overlap_score: Annotated[int, Field(ge=0)]
    evidence_ids: Annotated[list[EvidenceId], Field(max_length=10)]


class ScoreProjectCandidatesOutput(ToolModel):
    """Factual history-overlap scores in input order."""

    scores: Annotated[list[CandidateHistoryScore], Field(min_length=1, max_length=3)]


class GatewaySchemaDefinition(BaseModel):
    """The schema subset accepted by AgentCore Gateway Lambda targets."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: SchemaType
    description: str | None = None
    properties: dict[str, GatewaySchemaDefinition] | None = None
    required: list[str] | None = None
    items: GatewaySchemaDefinition | None = None

    @model_validator(mode="after")
    def require_shape_fields(self) -> Self:
        """Require nested schemas only for types that support them."""
        if self.type == "array" and self.items is None:
            raise ValueError("array schemas require items")
        if self.type != "array" and self.items is not None:
            raise ValueError("items is valid only for array schemas")
        if self.type != "object" and (self.properties is not None or self.required is not None):
            raise ValueError("properties and required are valid only for object schemas")
        if self.required and not set(self.required) <= set(self.properties or {}):
            raise ValueError("required fields must exist in properties")
        return self


class GatewayToolDefinition(BaseModel):
    """One AgentCore Gateway Lambda tool definition."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: ToolName
    description: Annotated[str, Field(min_length=1, max_length=200)]
    input_schema: GatewaySchemaDefinition = Field(alias="inputSchema")
    output_schema: GatewaySchemaDefinition = Field(alias="outputSchema")


@dataclass(frozen=True, slots=True)
class ToolContract:
    """Pair one MCP tool name with its strict runtime models."""

    name: ToolName
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]


TOOL_CONTRACTS = (
    ToolContract(
        name="search_catalog",
        description=(
            "Find relevant books, projects, technical artifacts, and museum objects using text "
            "and exact filters."
        ),
        input_model=SearchCatalogRequest,
        output_model=SearchCatalogOutput,
    ),
    ToolContract(
        name="get_catalog_item",
        description=(
            "Retrieve one evidence record using a stable evidence ID returned by another "
            "catalog tool."
        ),
        input_model=GetCatalogItemRequest,
        output_model=GetCatalogItemOutput,
    ),
    ToolContract(
        name="summarize_experience",
        description=(
            "Return prior projects sharing terms or programming languages with one proposed "
            "project."
        ),
        input_model=SummarizeExperienceInput,
        output_model=SummarizeExperienceOutput,
    ),
    ToolContract(
        name="score_project_candidates",
        description=(
            "Measure term and programming-language overlap for one to three proposals and "
            "return supporting evidence IDs."
        ),
        input_model=ScoreProjectCandidatesInput,
        output_model=ScoreProjectCandidatesOutput,
    ),
)
CONTRACTS_BY_NAME = {contract.name: contract for contract in TOOL_CONTRACTS}


def _schema_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("JSON Schema value must be an object")
    return cast("dict[str, object]", value)


def _schema_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("JSON Schema value must be an array")
    return cast("list[object]", value)


def _merge_object_variants(
    variants: list[GatewaySchemaDefinition],
) -> GatewaySchemaDefinition:
    properties: dict[str, GatewaySchemaDefinition] = {}
    required_sets: list[set[str]] = []
    for variant in variants:
        properties.update(variant.properties or {})
        required_sets.append(set(variant.required or ()))
    common_required: set[str] = required_sets[0].copy() if required_sets else set()
    for required_set in required_sets[1:]:
        common_required.intersection_update(required_set)
    return GatewaySchemaDefinition(
        type="object",
        properties=properties,
        required=sorted(common_required) or None,
    )


def _gateway_schema(
    schema: Mapping[str, object],
    definitions: Mapping[str, object],
) -> GatewaySchemaDefinition:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        name = reference.removeprefix("#/$defs/")
        return _gateway_schema(_schema_object(definitions[name]), definitions)

    variant_value = schema.get("anyOf", schema.get("oneOf"))
    if variant_value is not None:
        variant_schemas = [
            _schema_object(variant)
            for variant in _schema_list(variant_value)
            if _schema_object(variant).get("type") != "null"
        ]
        variants = [_gateway_schema(variant, definitions) for variant in variant_schemas]
        if len(variants) == 1:
            return variants[0]
        if variants and all(variant.type == "object" for variant in variants):
            return _merge_object_variants(variants)
        raise ValueError("Gateway schema cannot represent a heterogeneous scalar union")

    schema_type = schema.get("type")
    if schema_type not in {"string", "number", "object", "array", "boolean", "integer"}:
        raise ValueError(f"Unsupported Gateway schema type: {schema_type}")
    description = schema.get("description")
    description_value = description if isinstance(description, str) else None

    if schema_type == "object":
        raw_properties = _schema_object(schema.get("properties", {}))
        properties = {
            name: _gateway_schema(_schema_object(property_schema), definitions)
            for name, property_schema in raw_properties.items()
        }
        raw_required = schema.get("required", [])
        required = [item for item in _schema_list(raw_required) if isinstance(item, str)]
        return GatewaySchemaDefinition(
            type="object",
            description=description_value,
            properties=properties or None,
            required=required or None,
        )
    if schema_type == "array":
        return GatewaySchemaDefinition(
            type="array",
            description=description_value,
            items=_gateway_schema(_schema_object(schema["items"]), definitions),
        )
    return GatewaySchemaDefinition(
        type=cast("SchemaType", schema_type), description=description_value
    )


def _strict_schema(model: type[BaseModel]) -> dict[str, JsonValue]:
    schema = cast("dict[str, JsonValue]", model.model_json_schema(mode="validation"))
    schema["$schema"] = JSON_SCHEMA_DRAFT
    Draft202012Validator.check_schema(schema)
    return schema


def strict_tool_json_schemas() -> dict[ToolName, dict[str, dict[str, JsonValue]]]:
    """Return defensive copies of every full Draft 2020-12 runtime schema."""
    return {
        contract.name: {
            "input": deepcopy(_strict_schema(contract.input_model)),
            "output": deepcopy(_strict_schema(contract.output_model)),
        }
        for contract in TOOL_CONTRACTS
    }


def _gateway_model_schema(model: type[BaseModel]) -> GatewaySchemaDefinition:
    schema = _schema_object(model.model_json_schema(mode="validation"))
    definitions = _schema_object(schema.get("$defs", {}))
    return _gateway_schema(schema, definitions)


def gateway_tool_definitions() -> tuple[GatewayToolDefinition, ...]:
    """Project strict contracts into AgentCore Gateway's supported schema subset."""
    return tuple(
        GatewayToolDefinition(
            name=contract.name,
            description=contract.description,
            inputSchema=_gateway_model_schema(contract.input_model),
            outputSchema=_gateway_model_schema(contract.output_model),
        )
        for contract in TOOL_CONTRACTS
    )


def gateway_tool_definitions_json() -> str:
    """Render the deterministic artifact consumed by OpenTofu."""
    definitions = [
        definition.model_dump(by_alias=True, exclude_none=True)
        for definition in gateway_tool_definitions()
    ]
    return f"{json.dumps(definitions, indent=2)}\n"


def validate_tool_input(name: ToolName, payload: object) -> BaseModel:
    """Apply the canonical strict input model for one tool."""
    encoded = json.dumps(payload, separators=(",", ":"))
    return CONTRACTS_BY_NAME[name].input_model.model_validate_json(encoded)


def validate_tool_output(name: ToolName, payload: object) -> BaseModel:
    """Apply the canonical strict output model for one tool."""
    encoded = json.dumps(payload, separators=(",", ":"))
    return CONTRACTS_BY_NAME[name].output_model.model_validate_json(encoded)
