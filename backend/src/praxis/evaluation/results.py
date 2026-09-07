"""Versioned result contracts for measured evaluation baselines."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from praxis.domain import ProjectCandidateSet
from praxis.evaluation.models import EvaluationCategory, EvaluationModel

type AgentCoreEvaluatorId = Literal[
    "Builtin.GoalSuccessRate",
    "Builtin.Correctness",
    "Builtin.ToolSelectionAccuracy",
]
type AgentCoreEvaluationLevel = Literal["SESSION", "TRACE", "TOOL_CALL"]


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


class DeploymentIdentity(EvaluationModel):
    """Immutable AgentCore Runtime target used by a deployed evaluation."""

    endpoint_qualifier: str
    runtime_version: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,4}$")]
    container_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class BaselineMetadata(EvaluationModel):
    """Environment identity needed to reproduce a baseline."""

    generated_at: datetime
    model_id: str
    region: str
    dataset: DatasetIdentity
    source: SourceIdentity
    deployment: DeploymentIdentity | None = None


class TokenUsageResult(EvaluationModel):
    """Token use for one successful evaluation case."""

    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    cache_read_input_tokens: Annotated[int, Field(ge=0)] = 0
    cache_write_input_tokens: Annotated[int, Field(ge=0)] = 0


class AgentCoreEvaluationResult(EvaluationModel):
    """Sanitized result from one managed evaluator for one Runtime session."""

    evaluator_id: AgentCoreEvaluatorId
    level: AgentCoreEvaluationLevel
    status: Literal["completed", "failed"]
    result_count: Annotated[int, Field(ge=0)]
    score_count: Annotated[int, Field(ge=0)]
    average_score: float | None
    labels: list[str]
    token_usage: TokenUsageResult
    error_code: str | None = None


class AgentCoreEvaluatorSummary(EvaluationModel):
    """Aggregate managed-evaluator measurements over a complete suite."""

    evaluator_id: AgentCoreEvaluatorId
    completed_case_count: Annotated[int, Field(ge=0)]
    failed_case_count: Annotated[int, Field(ge=0)]
    result_count: Annotated[int, Field(ge=0)]
    score_count: Annotated[int, Field(ge=0)]
    average_score: float | None
    token_usage: TokenUsageResult


class ToolCallCount(EvaluationModel):
    """Observed call count for a named local or model-facing tool."""

    tool: str
    calls: Annotated[int, Field(ge=0)]


class MechanicalChecks(EvaluationModel):
    """Independent mechanical checks; none establish semantic answer quality."""

    structured_output_valid: bool
    citation_ids_retrieved: bool
    expected_evidence_met: bool
    expected_trajectory_met: bool


class RetrievalRelevanceResult(EvaluationModel):
    """Ranking-aware relevance measurements for one retrieval context."""

    retrieved_count: Annotated[int, Field(ge=0)]
    curated_relevant_count: Annotated[int, Field(ge=1)]
    matched_count: Annotated[int, Field(ge=0)]
    precision_at_k: Annotated[float, Field(ge=0, le=1)]
    expected_evidence_coverage: Annotated[float, Field(ge=0, le=1)]
    reciprocal_rank: Annotated[float, Field(ge=0, le=1)]


class CitationResolutionResult(EvaluationModel):
    """Count citations whose identifiers appear in the retrieval context."""

    citation_count: Annotated[int, Field(ge=0)]
    resolved_citation_count: Annotated[int, Field(ge=0)]
    unresolved_citation_count: Annotated[int, Field(ge=0)]
    citation_resolution_rate: Annotated[float, Field(ge=0, le=1)]


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
    checks: MechanicalChecks
    retrieval_relevance: RetrievalRelevanceResult | None = None
    citation_resolution: CitationResolutionResult | None = None
    agentcore_evaluations: list[AgentCoreEvaluationResult] = Field(
        default_factory=list[AgentCoreEvaluationResult], max_length=3
    )
    error_type: str | None = None
    error_message: str | None = None


class BaselineSummary(EvaluationModel):
    """Aggregate measurements over the complete suite."""

    case_count: Annotated[int, Field(ge=1)]
    success_count: Annotated[int, Field(ge=0)]
    expected_evidence_pass_count: Annotated[int, Field(ge=0)]
    expected_trajectory_pass_count: Annotated[int, Field(ge=0)]
    wall_latency_p50_ms: Annotated[int, Field(ge=0)]
    wall_latency_p95_ms: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    total_local_tool_calls: Annotated[int, Field(ge=0)]
    total_model_tool_calls: Annotated[int, Field(ge=0)]
    average_retrieval_precision_at_k: Annotated[float, Field(ge=0, le=1)] = 0.0
    average_expected_evidence_coverage: Annotated[float, Field(ge=0, le=1)] = 0.0
    mean_reciprocal_rank: Annotated[float, Field(ge=0, le=1)] = 0.0
    citation_count: Annotated[int, Field(ge=0)] = 0
    resolved_citation_count: Annotated[int, Field(ge=0)] = 0
    unresolved_citation_count: Annotated[int, Field(ge=0)] = 0
    citation_resolution_rate: Annotated[float, Field(ge=0, le=1)] = 0.0
    agentcore_evaluations: list[AgentCoreEvaluatorSummary] = Field(
        default_factory=list[AgentCoreEvaluatorSummary], max_length=3
    )


class BaselineResult(EvaluationModel):
    """One immutable project-recommendation model baseline artifact."""

    suite: Literal["project-recommendation-baseline"]
    prompts_version: Literal[1, 2]
    expectations_version: Literal[1, 2]
    result_version: Literal[5]
    metadata: BaselineMetadata
    summary: BaselineSummary
    cases: Annotated[list[EvaluationCaseResult], Field(min_length=10, max_length=30)]


__all__ = [
    "AgentCoreEvaluationLevel",
    "AgentCoreEvaluationResult",
    "AgentCoreEvaluatorId",
    "AgentCoreEvaluatorSummary",
    "BaselineMetadata",
    "BaselineResult",
    "BaselineSummary",
    "CitationResolutionResult",
    "DatasetIdentity",
    "DeploymentIdentity",
    "EvaluationCaseResult",
    "MechanicalChecks",
    "RetrievalRelevanceResult",
    "SourceIdentity",
    "TokenUsageResult",
    "ToolCallCount",
]
