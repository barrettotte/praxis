"""Tests for deployed Runtime evaluation measurements."""

import json

import pytest

from praxis.agent.runtime_smoke import RuntimeTraceResult, RuntimeTraceSpan
from praxis.catalog import InMemoryCatalog
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet
from praxis.evaluation.runtime import (
    RuntimeEvaluationError,
    RuntimeEvaluationInvoker,
    trace_generation_metrics,
)

RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"


class FakeBody:
    """In-memory stand-in for botocore's streaming response body."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


def _candidate_set() -> ProjectCandidateSet:
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides relevant implementation context.",
                estimated_scope="multi-week",
                technologies=["Python"],
                first_milestone="Implement and test one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0f5ba253568e4836",
                        generated_connection="The book covers compiler backend development.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def _span(
    operation: str,
    *,
    attributes: dict[str, object] | None = None,
    duration_nano: int | None = None,
    session_id: str = "test-session",
    span_id: str | None = None,
) -> RuntimeTraceSpan:
    span_attributes: dict[str, object] = {
        "gen_ai.operation.name": operation,
        "session.id": session_id,
    }
    span_attributes.update(attributes or {})
    return RuntimeTraceSpan.model_validate(
        {
            "scope": {"name": "strands.telemetry.tracer"},
            "traceId": "trace-id",
            "spanId": span_id or f"span-{operation}",
            "durationNano": duration_nano,
            "resource": {
                "attributes": {"cloud.resource_id": f"{RUNTIME_ARN}/runtime-endpoint/stable:8"}
            },
            "attributes": span_attributes,
        }
    )


def _trace(session_id: str = "test-session") -> RuntimeTraceResult:
    return RuntimeTraceResult(
        spans=(
            _span(
                "invoke_agent",
                session_id=session_id,
                attributes={
                    "gen_ai.usage.input_tokens": 100,
                    "gen_ai.usage.output_tokens": 50,
                    "gen_ai.usage.total_tokens": 150,
                },
            ),
            _span(
                "chat",
                session_id=session_id,
                span_id="span-chat-1",
                attributes={
                    "gen_ai.server.request.duration": 200,
                    "gen_ai.server.time_to_first_token": 40,
                },
            ),
            _span(
                "chat",
                session_id=session_id,
                duration_nano=250_000_000,
                span_id="span-chat-2",
            ),
            _span(
                "execute_tool",
                session_id=session_id,
                span_id="span-tool-1",
                attributes={"gen_ai.tool.name": "GatewayCandidateOutput"},
            ),
            _span(
                "execute_tool",
                session_id=session_id,
                span_id="span-tool-2",
                attributes={"gen_ai.tool.name": "GatewayCandidateOutput"},
            ),
            _span("execute_event_loop_cycle", session_id=session_id, span_id="span-cycle-1"),
            _span("execute_event_loop_cycle", session_id=session_id, span_id="span-cycle-2"),
        )
    )


def test_trace_generation_metrics_matches_local_measurement_contract() -> None:
    metrics = trace_generation_metrics(_trace())

    assert metrics.token_usage.input_tokens == 100
    assert metrics.token_usage.output_tokens == 50
    assert metrics.token_usage.total_tokens == 150
    assert metrics.model_latency_ms == 450
    assert metrics.time_to_first_byte_ms == 40
    assert metrics.model_tool_calls == (("GatewayCandidateOutput", 2),)
    assert metrics.cycle_count == 2


def test_trace_generation_metrics_requires_complete_agent_usage() -> None:
    trace = RuntimeTraceResult(spans=(_span("invoke_agent"), _span("chat", duration_nano=1)))

    with pytest.raises(RuntimeEvaluationError, match="missing token usage"):
        trace_generation_metrics(trace)


def test_runtime_invoker_adapts_response_tools_and_correlated_trace() -> None:
    candidates = _candidate_set()

    class FakeRuntimeClient:
        request: dict[str, object] | None = None

        def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
            self.request = kwargs
            payload = {
                "candidates": candidates.model_dump(mode="json")["candidates"],
                "memory": {"retrieved_count": 0},
                "tool_calls": [
                    {"name": "search_catalog", "count": 1},
                    {"name": "summarize_experience", "count": 1},
                ],
            }
            return {
                "statusCode": 200,
                "contentType": "application/json",
                "response": FakeBody(json.dumps(payload).encode()),
            }

    class FakeLogsClient:
        request: dict[str, object] | None = None

        def filter_log_events(self, **kwargs: object) -> dict[str, object]:
            self.request = kwargs
            session_id = str(kwargs["filterPattern"]).strip('"')
            return {
                "events": [
                    {"message": span.model_dump_json(by_alias=True)}
                    for span in _trace(session_id).spans
                ]
            }

    runtime_client = FakeRuntimeClient()
    logs_client = FakeLogsClient()
    invoker = RuntimeEvaluationInvoker(
        runtime_client=runtime_client,
        logs_client=logs_client,
        runtime_arn=RUNTIME_ARN,
        qualifier="stable",
        trace_timeout_seconds=1,
    )

    empty_catalog = InMemoryCatalog(books=(), projects=(), bytes=(), museum_objects=())
    result = invoker("compiler", empty_catalog, None)

    assert result.candidates == candidates
    assert result.retrieved_evidence_ids == ("book:0f5ba253568e4836",)
    assert result.local_tool_calls == ("search_catalog", "compare_project_history")
    assert result.generation_metrics == trace_generation_metrics(_trace())
    assert runtime_client.request is not None
    assert logs_client.request is not None
    session_id = str(runtime_client.request["runtimeSessionId"])
    request_payload = runtime_client.request["payload"]
    assert isinstance(request_payload, bytes)
    assert json.loads(request_payload)["actor_id"] == "praxis-evaluation"
    assert session_id in str(logs_client.request["filterPattern"])
