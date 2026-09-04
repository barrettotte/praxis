"""Score correlated Runtime traces with managed AgentCore evaluators."""

from collections.abc import Iterable, Sequence
from typing import Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from praxis.agent.runtime_smoke import RuntimeTraceResult
from praxis.evaluation.results import (
    AgentCoreEvaluationLevel,
    AgentCoreEvaluationResult,
    AgentCoreEvaluatorId,
    TokenUsageResult,
)

GOAL_SUCCESS_EVALUATOR = "Builtin.GoalSuccessRate"
CORRECTNESS_EVALUATOR = "Builtin.Correctness"
TOOL_SELECTION_EVALUATOR = "Builtin.ToolSelectionAccuracy"
MANAGED_EVALUATORS: tuple[AgentCoreEvaluatorId, ...] = (
    GOAL_SUCCESS_EVALUATOR,
    CORRECTNESS_EVALUATOR,
    TOOL_SELECTION_EVALUATOR,
)


class AgentCoreEvaluationClient(Protocol):
    """AgentCore data-plane method used for on-demand evaluation."""

    def evaluate(self, **kwargs: object) -> dict[str, object]: ...


class _RawTokenUsage(BaseModel):
    """Token counts returned for one managed evaluator result."""

    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    total_tokens: int = Field(default=0, alias="totalTokens")


class _RawEvaluationResult(BaseModel):
    """Non-sensitive fields read from one managed evaluator result."""

    model_config = ConfigDict(extra="ignore")

    value: float | None = None
    label: str | None = None
    token_usage: _RawTokenUsage = Field(default_factory=_RawTokenUsage, alias="tokenUsage")
    error_code: str | None = Field(default=None, alias="errorCode")


RAW_RESULTS = TypeAdapter(list[_RawEvaluationResult])


def _error_code(error: Exception) -> str:
    """Return a stable error classification without retaining service messages."""
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code")
        if isinstance(code, str) and code:
            return code
    return type(error).__name__


def _failed_result(
    evaluator_id: AgentCoreEvaluatorId,
    level: AgentCoreEvaluationLevel,
    error_code: str,
) -> AgentCoreEvaluationResult:
    return AgentCoreEvaluationResult(
        evaluator_id=evaluator_id,
        level=level,
        status="failed",
        result_count=0,
        score_count=0,
        average_score=None,
        labels=[],
        token_usage=TokenUsageResult(input_tokens=0, output_tokens=0, total_tokens=0),
        error_code=error_code,
    )


def _summarize_response(
    evaluator_id: AgentCoreEvaluatorId,
    level: AgentCoreEvaluationLevel,
    response: dict[str, object],
) -> AgentCoreEvaluationResult:
    """Reduce service output to scores and counts safe for result artifacts."""
    try:
        results = RAW_RESULTS.validate_python(response.get("evaluationResults"))
    except ValidationError:
        return _failed_result(evaluator_id, level, "InvalidEvaluationResponse")
    if not results:
        return _failed_result(evaluator_id, level, "EmptyEvaluationResponse")

    service_errors = sorted({result.error_code for result in results if result.error_code})
    scores = [result.value for result in results if result.value is not None]
    token_usage = TokenUsageResult(
        input_tokens=sum(result.token_usage.input_tokens for result in results),
        output_tokens=sum(result.token_usage.output_tokens for result in results),
        total_tokens=sum(result.token_usage.total_tokens for result in results),
    )
    return AgentCoreEvaluationResult(
        evaluator_id=evaluator_id,
        level=level,
        status="failed" if service_errors else "completed",
        result_count=len(results),
        score_count=len(scores),
        average_score=sum(scores) / len(scores) if scores else None,
        labels=sorted({result.label for result in results if result.label}),
        token_usage=token_usage,
        error_code=",".join(service_errors) if service_errors else None,
    )


def _evaluate(
    client: AgentCoreEvaluationClient,
    evaluator_id: AgentCoreEvaluatorId,
    level: AgentCoreEvaluationLevel,
    spans: list[dict[str, object]],
    *,
    target: dict[str, list[str]] | None = None,
    references: list[dict[str, object]] | None = None,
) -> AgentCoreEvaluationResult:
    request: dict[str, object] = {
        "evaluatorId": evaluator_id,
        "evaluationInput": {"sessionSpans": spans},
    }
    if target is not None:
        request["evaluationTarget"] = target
    if references is not None:
        request["evaluationReferenceInputs"] = references
    try:
        response = client.evaluate(**request)
    except (BotoCoreError, ClientError) as error:
        return _failed_result(evaluator_id, level, _error_code(error))
    return _summarize_response(evaluator_id, level, response)


def evaluate_runtime_trace(
    client: AgentCoreEvaluationClient,
    trace: RuntimeTraceResult,
    session_id: str,
    assertions: Sequence[str],
) -> tuple[AgentCoreEvaluationResult, ...]:
    """Run goal, correctness, and tool-selection scoring for one session."""
    spans = [
        cast("dict[str, object]", span.model_dump(mode="json", by_alias=True, exclude_none=True))
        for span in trace.spans
    ]
    trace_ids = sorted({span.trace_id for span in trace.spans})
    tool_span_ids = sorted(
        span.span_id
        for span in trace.spans
        if span.scope.name == "strands.telemetry.tracer"
        and span.attributes.get("gen_ai.operation.name") == "execute_tool"
    )
    reference: dict[str, object] = {
        "context": {"spanContext": {"sessionId": session_id}},
        "assertions": [{"text": assertion} for assertion in assertions],
    }

    results = [
        _evaluate(
            client,
            GOAL_SUCCESS_EVALUATOR,
            "SESSION",
            spans,
            references=[reference],
        ),
        _evaluate(
            client,
            CORRECTNESS_EVALUATOR,
            "TRACE",
            spans,
            target={"traceIds": trace_ids},
        ),
    ]
    if tool_span_ids:
        results.append(
            _evaluate(
                client,
                TOOL_SELECTION_EVALUATOR,
                "TOOL_CALL",
                spans,
                target={"spanIds": tool_span_ids},
            )
        )
    else:
        results.append(_failed_result(TOOL_SELECTION_EVALUATOR, "TOOL_CALL", "NoToolSpans"))
    return tuple(results)


def evaluation_failed(results: Iterable[AgentCoreEvaluationResult]) -> bool:
    """Return whether any required managed evaluator failed."""
    return any(result.status == "failed" for result in results)


__all__ = [
    "MANAGED_EVALUATORS",
    "AgentCoreEvaluationClient",
    "evaluate_runtime_trace",
    "evaluation_failed",
]
