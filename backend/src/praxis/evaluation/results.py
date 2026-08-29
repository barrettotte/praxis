"""Versioned result contracts for measured evaluation baselines."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from praxis.domain import ProjectCandidateSet
from praxis.evaluation.models import EvaluationCategory, EvaluationModel


class DatasetIdentity(EvaluationModel):
    """Non-sensitive identity of the catalog snapshot used by a run."""

    label: str
    record_count: Annotated[int, Field(ge=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceIdentity(EvaluationModel):
    """Revision and content identity of the code under evaluation."""

    git_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    working_tree_dirty: bool
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BaselineMetadata(EvaluationModel):
    """Environment identity needed to reproduce a baseline."""

    generated_at: datetime
    model_id: str
    region: str
    dataset: DatasetIdentity
    source: SourceIdentity


class TokenUsageResult(EvaluationModel):
    """Token use for one successful evaluation case."""

    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    cache_read_input_tokens: Annotated[int, Field(ge=0)] = 0
    cache_write_input_tokens: Annotated[int, Field(ge=0)] = 0


class ToolCallCount(EvaluationModel):
    """Observed call count for a named local or model-facing tool."""

    tool: str
    calls: Annotated[int, Field(ge=0)]


class QualityResult(EvaluationModel):
    """Deterministic quality checks for one generated candidate set."""

    structured_output_valid: bool
    citations_grounded: bool
    expected_evidence_met: bool
    expected_trajectory_met: bool
    concrete_first_milestones: bool
    score: Annotated[float, Field(ge=0, le=1)]


class EvaluationCaseResult(EvaluationModel):
    """Measured output and checks for one stable evaluation case."""

    case_id: str
    category: EvaluationCategory
    succeeded: bool
    candidates: ProjectCandidateSet | None
    retrieved_evidence_ids: list[str]
    cited_evidence_ids: list[str]
    local_tool_calls: list[ToolCallCount]
    model_tool_calls: list[ToolCallCount]
    wall_latency_ms: Annotated[int, Field(ge=0)]
    model_latency_ms: Annotated[int, Field(ge=0)] | None
    time_to_first_byte_ms: Annotated[int, Field(ge=0)] | None
    token_usage: TokenUsageResult | None
    cycle_count: Annotated[int, Field(ge=0)] | None
    quality: QualityResult
    error_type: str | None = None
    error_message: str | None = None


class BaselineSummary(EvaluationModel):
    """Aggregate measurements over the complete suite."""

    case_count: Annotated[int, Field(ge=1)]
    success_count: Annotated[int, Field(ge=0)]
    average_quality_score: Annotated[float, Field(ge=0, le=1)]
    expected_evidence_pass_count: Annotated[int, Field(ge=0)]
    expected_trajectory_pass_count: Annotated[int, Field(ge=0)]
    concrete_milestone_pass_count: Annotated[int, Field(ge=0)]
    wall_latency_p50_ms: Annotated[int, Field(ge=0)]
    wall_latency_p95_ms: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    total_local_tool_calls: Annotated[int, Field(ge=0)]
    total_model_tool_calls: Annotated[int, Field(ge=0)]


class BaselineResult(EvaluationModel):
    """One immutable project-recommendation Nova baseline artifact."""

    suite: Literal["project-recommendation-baseline"]
    prompts_version: Literal[1]
    expectations_version: Literal[1]
    result_version: Literal[1]
    metadata: BaselineMetadata
    summary: BaselineSummary
    cases: Annotated[list[EvaluationCaseResult], Field(min_length=10, max_length=10)]


__all__ = [
    "BaselineMetadata",
    "BaselineResult",
    "BaselineSummary",
    "DatasetIdentity",
    "EvaluationCaseResult",
    "QualityResult",
    "SourceIdentity",
    "TokenUsageResult",
    "ToolCallCount",
]
