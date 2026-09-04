"""Tests for privacy-safe on-demand AgentCore evaluation scoring."""

from typing import cast

from botocore.exceptions import ClientError

from praxis.agent.runtime_smoke import RuntimeTraceResult, RuntimeTraceSpan
from praxis.evaluation.agentcore import (
    CORRECTNESS_EVALUATOR,
    GOAL_SUCCESS_EVALUATOR,
    TOOL_SELECTION_EVALUATOR,
    evaluate_runtime_trace,
    evaluation_failed,
)


def _span(operation: str, span_id: str) -> RuntimeTraceSpan:
    return RuntimeTraceSpan.model_validate(
        {
            "name": operation,
            "scope": {"name": "strands.telemetry.tracer"},
            "traceId": "trace-1",
            "spanId": span_id,
            "startTimeUnixNano": 100,
            "endTimeUnixNano": 200,
            "resource": {"attributes": {"service.name": "praxis-agent"}},
            "attributes": {
                "gen_ai.operation.name": operation,
                "session.id": "session-1",
            },
        }
    )


def _trace(*, include_tool: bool = True) -> RuntimeTraceResult:
    spans = [_span("invoke_agent", "span-agent"), _span("chat", "span-chat")]
    if include_tool:
        spans.append(_span("execute_tool", "span-tool"))
    return RuntimeTraceResult(spans=tuple(spans))


class FakeEvaluationClient:
    """Record evaluator requests and return predictable service-shaped scores."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        evaluator_id = str(kwargs["evaluatorId"])
        return {
            "evaluationResults": [
                {
                    "evaluatorId": evaluator_id,
                    "value": 0.75,
                    "label": "PASS",
                    "tokenUsage": {
                        "inputTokens": 10,
                        "outputTokens": 2,
                        "totalTokens": 12,
                    },
                    # Explanations must never enter the sanitized result contract.
                    "explanation": "The response included private trace content.",
                }
            ]
        }


def test_evaluate_runtime_trace_targets_each_supported_level() -> None:
    client = FakeEvaluationClient()

    results = evaluate_runtime_trace(
        client,
        _trace(),
        "session-1",
        ["Recommendations respect the user's time constraint."],
    )

    assert [result.evaluator_id for result in results] == [
        GOAL_SUCCESS_EVALUATOR,
        CORRECTNESS_EVALUATOR,
        TOOL_SELECTION_EVALUATOR,
    ]
    assert all(result.status == "completed" for result in results)
    assert all(result.average_score == 0.75 for result in results)
    assert all(result.token_usage.total_tokens == 12 for result in results)
    assert not evaluation_failed(results)

    goal, correctness, tool_selection = client.requests
    assert "evaluationTarget" not in goal
    assert goal["evaluationReferenceInputs"] == [
        {
            "context": {"spanContext": {"sessionId": "session-1"}},
            "assertions": [{"text": "Recommendations respect the user's time constraint."}],
        }
    ]
    assert correctness["evaluationTarget"] == {"traceIds": ["trace-1"]}
    assert tool_selection["evaluationTarget"] == {"spanIds": ["span-tool"]}

    evaluation_input = cast("dict[str, object]", goal["evaluationInput"])
    session_spans = cast("list[dict[str, object]]", evaluation_input["sessionSpans"])
    assert session_spans[0]["startTimeUnixNano"] == 100


def test_evaluate_runtime_trace_records_missing_tool_spans_without_calling_service() -> None:
    client = FakeEvaluationClient()

    results = evaluate_runtime_trace(client, _trace(include_tool=False), "session-1", ["Safe"])

    assert len(client.requests) == 2
    assert results[-1].evaluator_id == TOOL_SELECTION_EVALUATOR
    assert results[-1].status == "failed"
    assert results[-1].error_code == "NoToolSpans"
    assert evaluation_failed(results)


def test_evaluate_runtime_trace_sanitizes_service_failures() -> None:
    class FailingClient:
        def evaluate(self, **_kwargs: object) -> dict[str, object]:
            raise ClientError(
                {
                    "Error": {
                        "Code": "AccessDeniedException",
                        "Message": "sensitive service detail",
                    }
                },
                "Evaluate",
            )

    results = evaluate_runtime_trace(FailingClient(), _trace(), "session-1", ["Safe"])

    assert all(result.status == "failed" for result in results)
    assert all(result.error_code == "AccessDeniedException" for result in results)
