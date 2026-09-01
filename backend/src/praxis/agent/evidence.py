"""Invocation-scoped evidence collection and conflict detection."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from strands.hooks import AfterToolCallEvent, HookRegistry
from strands.types.tools import ToolResult

from praxis.tools.contracts import (
    CONTRACTS_BY_NAME,
    GetCatalogItemOutput,
    ScoreProjectCandidatesOutput,
    SearchCatalogOutput,
    SummarizeExperienceOutput,
    ToolName,
    validate_tool_output,
)

_EVIDENCE_FACTS_KEY = "praxis.evidence_facts"
_CONFLICTING_EVIDENCE_IDS_KEY = "praxis.conflicting_evidence_ids"


@dataclass(frozen=True, slots=True)
class EvidenceState:
    """Evidence identity and conflict state observed during one invocation."""

    evidence_ids: frozenset[str]
    conflicting_ids: frozenset[str]
    ordered_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogEvidenceLedger:
    """Collect strict catalog evidence and reject conflicting factual observations."""

    def register_hooks(self, registry: HookRegistry, **_: object) -> None:
        """Register evidence collection after successful tool execution."""
        registry.add_callback(AfterToolCallEvent, self.after_tool_call)

    def after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Record accepted evidence or replace a conflicting result with an error."""
        tool_name = event.tool_use["name"]
        if tool_name not in CONTRACTS_BY_NAME or event.result["status"] != "success":
            return

        raw_result = cast("dict[str, object]", event.result)
        try:
            observations = _evidence_observations(
                cast("ToolName", tool_name),
                catalog_result_payload(raw_result),
            )
        except (TypeError, ValueError):
            event.result = _error_result(event, "Catalog tool returned invalid evidence")
            return

        conflict_message = _record_observations(observations, event.invocation_state)
        if conflict_message is not None:
            event.result = _error_result(event, conflict_message)


def catalog_result_payload(result: Mapping[str, object]) -> dict[str, object]:
    """Extract a catalog payload from either MCP SDK result representation."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return cast("dict[str, object]", structured)

    content = result.get("content")
    if isinstance(content, list):
        for value in cast("list[object]", content):
            if not isinstance(value, dict):
                continue
            item = cast("dict[str, object]", value)
            json_value = item.get("json")
            if isinstance(json_value, dict):
                return cast("dict[str, object]", json_value)
            text = item.get("text")
            if isinstance(text, str):
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    return cast("dict[str, object]", decoded)
    raise ValueError("Gateway tool response contains no structured catalog payload")


def record_catalog_evidence(
    tool_name: ToolName,
    payload: object,
    invocation_state: dict[str, object],
) -> str | None:
    """Validate and retain one catalog response, returning a safe conflict message."""
    return _record_observations(
        _evidence_observations(tool_name, payload),
        invocation_state,
    )


def _record_observations(
    observations: list[tuple[str, dict[str, object]]],
    invocation_state: dict[str, object],
) -> str | None:
    """Merge validated observations into the invocation ledger."""
    facts = _evidence_facts(invocation_state)
    updates: dict[str, dict[str, object]] = {}
    conflicting_ids: set[str] = set()
    for evidence_id, observed in observations:
        known = facts.get(evidence_id, {}) | updates.get(evidence_id, {})
        if any(key in known and known[key] != value for key, value in observed.items()):
            conflicting_ids.add(evidence_id)
        updates.setdefault(evidence_id, {}).update(observed)

    if conflicting_ids:
        _conflicting_ids(invocation_state).update(conflicting_ids)
        listed_ids = ", ".join(sorted(conflicting_ids))
        return f"Conflicting catalog facts detected for evidence: {listed_ids}"

    for evidence_id, observed in updates.items():
        facts.setdefault(evidence_id, {}).update(observed)
    return None


def read_evidence_state(invocation_state: dict[str, object]) -> EvidenceState:
    """Return an immutable view of evidence collected by the Gateway agent."""
    evidence_ids = tuple(_evidence_facts(invocation_state))
    return EvidenceState(
        evidence_ids=frozenset(evidence_ids),
        conflicting_ids=frozenset(_conflicting_ids(invocation_state)),
        ordered_evidence_ids=evidence_ids,
    )


def _evidence_facts(invocation_state: dict[str, object]) -> dict[str, dict[str, object]]:
    value = invocation_state.setdefault(_EVIDENCE_FACTS_KEY, {})
    if not isinstance(value, dict):
        raise TypeError("Evidence facts state must be an object")
    return cast("dict[str, dict[str, object]]", value)


def _conflicting_ids(invocation_state: dict[str, object]) -> set[str]:
    value = invocation_state.setdefault(_CONFLICTING_EVIDENCE_IDS_KEY, set[str]())
    if not isinstance(value, set):
        raise TypeError("Conflicting evidence state must be a set")
    return cast("set[str]", value)


def _evidence_observations(
    tool_name: ToolName,
    payload: object,
) -> list[tuple[str, dict[str, object]]]:
    """Validate a catalog response and project only stable factual fields."""
    validated = validate_tool_output(tool_name, payload)
    match validated:
        case SearchCatalogOutput():
            return [
                (
                    result.evidence_id,
                    cast(
                        "dict[str, object]",
                        result.model_dump(
                            mode="json",
                            exclude={"evidence_id", "score"},
                            exclude_none=True,
                        ),
                    ),
                )
                for result in validated.results
            ]
        case GetCatalogItemOutput():
            return [
                (
                    validated.item.evidence_id,
                    cast(
                        "dict[str, object]",
                        validated.item.model_dump(
                            mode="json",
                            exclude={"evidence_id"},
                            exclude_none=True,
                        ),
                    ),
                )
            ]
        case SummarizeExperienceOutput():
            return [
                (
                    match.evidence_id,
                    cast(
                        "dict[str, object]",
                        match.model_dump(
                            mode="json",
                            include={"name", "date"},
                            exclude_none=True,
                        )
                        | {"kind": "project"},
                    ),
                )
                for match in validated.matches
            ]
        case ScoreProjectCandidatesOutput():
            return [
                (evidence_id, {"kind": "project"})
                for score in validated.scores
                for evidence_id in score.evidence_ids
            ]
        case _:
            raise TypeError(f"Unsupported catalog result type: {type(validated).__name__}")


def _error_result(event: AfterToolCallEvent, message: str) -> ToolResult:
    """Return an error without retaining conflicting catalog content."""
    return {
        "toolUseId": event.tool_use["toolUseId"],
        "status": "error",
        "content": [{"text": message}],
    }
