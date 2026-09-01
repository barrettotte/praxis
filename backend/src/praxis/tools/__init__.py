"""Strict contracts for tools exposed through AgentCore Gateway."""

from praxis.tools.contracts import (
    MAX_CANDIDATE_SCORE_EVIDENCE_IDS,
    GatewayToolDefinition,
    ScoreProjectCandidatesInput,
    ScoreProjectCandidatesOutput,
    SearchCatalogOutput,
    SummarizeExperienceInput,
    SummarizeExperienceOutput,
    gateway_tool_definitions,
    gateway_tool_definitions_json,
    strict_tool_json_schemas,
    validate_tool_input,
    validate_tool_output,
)

__all__ = [
    "MAX_CANDIDATE_SCORE_EVIDENCE_IDS",
    "GatewayToolDefinition",
    "ScoreProjectCandidatesInput",
    "ScoreProjectCandidatesOutput",
    "SearchCatalogOutput",
    "SummarizeExperienceInput",
    "SummarizeExperienceOutput",
    "gateway_tool_definitions",
    "gateway_tool_definitions_json",
    "strict_tool_json_schemas",
    "validate_tool_input",
    "validate_tool_output",
]
