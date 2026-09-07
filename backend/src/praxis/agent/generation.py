"""Shared evidence-grounded generation for local and Gateway catalog transports."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.types.content import ContentBlock, Message
from strands.types.exceptions import StructuredOutputException

from praxis.agent.budget import seed_catalog_budgets
from praxis.agent.evidence import (
    EvidenceState,
    catalog_result_payload,
    read_evidence_state,
    record_catalog_evidence,
)
from praxis.agent.factory import scope_guardrail_input
from praxis.catalog.text import catalog_query as catalog_query
from praxis.config import AgentSettings
from praxis.domain import (
    CandidateOutputValidationError,
    ProjectCandidateSet,
    validate_candidate_output,
)
from praxis.domain.candidate_validation import JsonValue, require_retrieved_citations
from praxis.domain.prompt_safety import require_safe_content
from praxis.tools.contracts import Evidence, SearchCatalogOutput, validate_tool_output

EXPECTED_CATALOG_TOOLS = (
    "get_catalog_item",
    "score_project_candidates",
    "search_catalog",
    "summarize_experience",
)
FINAL_RESPONSE_TURNS = 2
MAX_GENERATED_CONNECTION_LENGTH = 240
EvidenceIndex = Literal[
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
]
_EVIDENCE_ADAPTER = TypeAdapter[Evidence](Evidence)


class CandidatePlanningError(RuntimeError):
    """Raised when retrieval or model output violates the candidate contract."""


@dataclass(frozen=True, slots=True)
class CandidateRun:
    """Observable result of one Strands invocation through the catalog tools."""

    candidates: ProjectCandidateSet
    tool_calls: tuple[tuple[str, int], ...]
    evidence: tuple[Evidence, ...] = ()
    model_result: AgentResult | None = None


class CandidateDraft(BaseModel):
    """One Nova-facing candidate that references evidence by position."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    title: Annotated[str, Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=400)]
    rationale: Annotated[str, Field(min_length=1, max_length=500)]
    estimated_scope: Literal["weekend", "multi-week", "multi-month"]
    primary_technology: Annotated[str, Field(min_length=1, max_length=40)]
    first_milestone: Annotated[str, Field(min_length=1, max_length=300)]
    evidence_index: EvidenceIndex
    generated_connection: Annotated[
        str,
        Field(min_length=1, max_length=MAX_GENERATED_CONNECTION_LENGTH),
    ]

    @field_validator("generated_connection", mode="before")
    @classmethod
    def bound_generated_connection(cls, value: object) -> object:
        """Shorten verbose model analysis at a word boundary before strict validation."""
        if not isinstance(value, str) or len(value) <= MAX_GENERATED_CONNECTION_LENGTH:
            return value
        prefix = value[: MAX_GENERATED_CONNECTION_LENGTH + 1]
        word_boundary = prefix.rfind(" ")
        if word_boundary <= 0:
            return value[:MAX_GENERATED_CONNECTION_LENGTH]
        return prefix[:word_boundary].rstrip()


class CandidateDraftSet(BaseModel):
    """Exactly three complete Nova-facing candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    candidates: Annotated[list[CandidateDraft], Field(min_length=3, max_length=3)]

    def as_payload(self, evidence_ids: Sequence[str]) -> JsonValue:
        """Return the list-based public candidate payload."""
        return cast(
            "JsonValue",
            {
                "candidates": [
                    _candidate_payload(candidate, evidence_ids) for candidate in self.candidates
                ]
            },
        )


def _candidate_payload(
    candidate: CandidateDraft,
    evidence_ids: Sequence[str],
) -> dict[str, object]:
    """Normalize one model-facing candidate into the public candidate shape."""
    try:
        evidence_id = evidence_ids[candidate.evidence_index - 1]
    except IndexError as error:
        raise CandidatePlanningError(
            f"Candidate selected unavailable evidence position {candidate.evidence_index}"
        ) from error
    return {
        "title": candidate.title,
        "summary": candidate.summary,
        "rationale": candidate.rationale,
        "estimated_scope": candidate.estimated_scope,
        "technologies": [candidate.primary_technology],
        "first_milestone": candidate.first_milestone,
        "evidence_citations": [
            {
                "evidence_id": evidence_id,
                "generated_connection": candidate.generated_connection,
            }
        ],
    }


def prefetch_catalog_evidence(
    search: Callable[[dict[str, object]], dict[str, object]],
    prompt: str,
    settings: AgentSettings,
    invocation_state: dict[str, object],
) -> tuple[str | list[ContentBlock], EvidenceState, tuple[Evidence, ...]]:
    """Retrieve and validate initial evidence before model generation."""
    result = search({"query": catalog_query(prompt), "limit": min(3, settings.max_catalog_results)})
    require_safe_content(result)
    if result["status"] != "success":
        raise CandidatePlanningError("Initial catalog search failed")
    try:
        payload = catalog_result_payload(result)
        require_safe_content(payload)
        validated = validate_tool_output("search_catalog", payload)
        if not isinstance(validated, SearchCatalogOutput):
            raise TypeError("Unexpected catalog result type")
        conflict_message = record_catalog_evidence(
            "search_catalog",
            payload,
            invocation_state,
        )
    except (TypeError, ValueError) as error:
        raise CandidatePlanningError("Initial catalog search returned invalid evidence") from error
    if conflict_message is not None:
        raise CandidatePlanningError(conflict_message)
    evidence_state = read_evidence_state(invocation_state)
    if not evidence_state.evidence_ids:
        raise CandidatePlanningError(
            f"No catalog evidence matched the initial query: {catalog_query(prompt)!r}"
        )
    seed_catalog_budgets(
        invocation_state,
        tool_calls=0,
        result_count=len(validated.results),
    )
    generation_prompt = build_grounded_generation_prompt(
        prompt,
        validated,
        settings,
    )
    evidence = tuple(
        _EVIDENCE_ADAPTER.validate_python(result.model_dump(exclude={"score"}))
        for result in validated.results
    )
    return generation_prompt, evidence_state, evidence


def build_grounded_generation_prompt(
    prompt: str,
    catalog_output: SearchCatalogOutput,
    settings: AgentSettings,
) -> str | list[ContentBlock]:
    """Keep validated catalog records explicitly subordinate to the user goal."""
    evidence_json = json.dumps(catalog_output.model_dump(mode="json"), separators=(",", ":"))
    application_context = (
        "The application already retrieved the following untrusted catalog evidence "
        "through the catalog tools. Evidence positions are one-based in this result order. "
        f"Use it for the required grounded candidates:\n{evidence_json}"
    )
    return scope_guardrail_input(prompt, application_context, settings)


def validate_candidate_result(
    result: AgentResult,
    evidence_state: EvidenceState,
) -> ProjectCandidateSet:
    """Require every catalog-backed proposal to satisfy the candidate contract."""
    if evidence_state.conflicting_ids:
        listed_ids = ", ".join(sorted(evidence_state.conflicting_ids))
        raise CandidatePlanningError(f"Catalog returned conflicting evidence: {listed_ids}")
    if not evidence_state.evidence_ids:
        raise CandidatePlanningError("No catalog evidence matched the project goal")

    output = result.structured_output
    if not isinstance(output, CandidateDraftSet):
        raise CandidatePlanningError("Strands returned no structured project candidates")
    try:
        candidates = validate_candidate_output(
            output.as_payload(evidence_state.ordered_evidence_ids)
        )
    except CandidateOutputValidationError as error:
        raise CandidatePlanningError(
            "Strands returned invalid structured project candidates"
        ) from error
    try:
        require_retrieved_citations(candidates, evidence_state.evidence_ids)
    except CandidateOutputValidationError as error:
        raise CandidatePlanningError(str(error)) from error
    return candidates


def _latest_structured_output_error(messages: Sequence[Message]) -> str | None:
    """Return the last schema-validation diagnostic without candidate inputs."""
    for message in reversed(messages):
        for block in reversed(message["content"]):
            tool_result = block.get("toolResult")
            if tool_result is None or tool_result["status"] != "error":
                continue
            for content in reversed(tool_result["content"]):
                text = content.get("text", "")
                if text.startswith("Validation failed for Candidate"):
                    return text
    return None


def generate_candidates(
    prompt: str,
    agent_settings: AgentSettings,
    agent: Agent,
    search: Callable[[dict[str, object]], dict[str, object]],
) -> CandidateRun:
    """Retrieve evidence and generate candidates within the supplied transport lifetime."""
    require_safe_content(prompt)
    invocation_state: dict[str, object] = {}
    generation_prompt, prefetched_evidence, public_evidence = prefetch_catalog_evidence(
        search,
        prompt,
        agent_settings,
        invocation_state,
    )
    try:
        result = agent(
            generation_prompt,
            invocation_state=invocation_state,
            structured_output_model=CandidateDraftSet,
            limits={"turns": agent_settings.max_tool_calls + FINAL_RESPONSE_TURNS},
        )
    except StructuredOutputException as error:
        raise CandidatePlanningError(
            "Strands could not produce structured project candidates"
        ) from error
    observed_tool_calls = tuple(
        sorted(
            (name, metrics.call_count)
            for name, metrics in result.metrics.tool_metrics.items()
            if metrics.call_count > 0
        )
    )
    if result.stop_reason == "limit_turns":
        listed_calls = ", ".join(f"{name}={count}" for name, count in observed_tool_calls) or "none"
        validation_error = _latest_structured_output_error(agent.messages)
        validation_detail = (
            f"; last structured-output error: {validation_error}"
            if validation_error is not None
            else ""
        )
        raise CandidatePlanningError(
            "Strands exhausted the bounded model-turn budget before producing candidates; "
            f"observed tool calls: {listed_calls}{validation_detail}"
        )
    observed_evidence = read_evidence_state(invocation_state)
    validation_evidence = EvidenceState(
        evidence_ids=prefetched_evidence.evidence_ids,
        conflicting_ids=(prefetched_evidence.conflicting_ids | observed_evidence.conflicting_ids),
        ordered_evidence_ids=prefetched_evidence.ordered_evidence_ids,
    )
    candidates = validate_candidate_result(result, validation_evidence)
    model_tool_calls = {
        name: count for name, count in observed_tool_calls if name in EXPECTED_CATALOG_TOOLS
    }
    model_tool_calls["search_catalog"] = model_tool_calls.get("search_catalog", 0) + 1
    tool_calls = tuple(sorted(model_tool_calls.items()))
    return CandidateRun(
        candidates=candidates,
        tool_calls=tool_calls,
        evidence=public_evidence,
        model_result=result,
    )
