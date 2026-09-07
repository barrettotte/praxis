"""Tests for signed AgentCore Runtime smoke validation."""

import json

import pytest

from praxis.agent.runtime_smoke import (
    RuntimeSmokeError,
    RuntimeToolCall,
    RuntimeTraceResult,
    RuntimeTraceSpan,
    invoke_runtime_endpoint,
    parse_runtime_traces,
    runtime_trace_log_group,
    wait_for_runtime_traces,
)
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet


class FakeBody:
    """In-memory stand-in for botocore's streaming response body."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeRuntimeClient:
    """Capture one Runtime invocation and return a configured response."""

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.request: dict[str, object] | None = None

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
        self.request = kwargs
        return self.response


def candidate_set(evidence_id: str = "book:0f5ba253568e4836") -> ProjectCandidateSet:
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides relevant implementation context.",
                estimated_scope="multi-week",
                technologies=["Python"],
                first_milestone="Implement one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id=evidence_id,
                        generated_connection="The book covers compiler backend development.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def evidence_record(evidence_id: str = "book:0f5ba253568e4836") -> dict[str, object]:
    if evidence_id.startswith("museum:"):
        return {
            "evidence_id": evidence_id,
            "kind": "museum",
            "name": "Example computer",
            "manufacturer": "Example manufacturer",
            "year": 1980,
            "category": "Computer",
            "description": "A representative museum object.",
        }
    return {
        "evidence_id": evidence_id,
        "kind": "book",
        "title": "Compiler Backend Development",
        "author": "Example Author",
        "year": 2025,
        "category": "Compilers",
        "tags": [],
    }


def valid_response() -> dict[str, object]:
    payload = {
        "candidates": candidate_set().model_dump(mode="json")["candidates"],
        "evidence": [evidence_record()],
        "tool_calls": [{"name": "search_catalog", "count": 1}],
    }
    return {
        "statusCode": 200,
        "contentType": "application/json",
        "response": FakeBody(json.dumps(payload).encode()),
    }


def test_invoke_runtime_endpoint_signs_expected_request_contract() -> None:
    client = FakeRuntimeClient(valid_response())
    session_id = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"

    result = invoke_runtime_endpoint(
        client,
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime",
        "stable",
        "  Recommend a compiler project  ",
        session_id,
    )

    assert client.request == {
        "accept": "application/json",
        "agentRuntimeArn": (
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"
        ),
        "contentType": "application/json",
        "payload": (b'{"prompt": "Recommend a compiler project"}'),
        "qualifier": "stable",
        "runtimeSessionId": session_id,
    }
    assert result.candidates == candidate_set()
    assert result.tool_calls == (RuntimeToolCall(name="search_catalog", count=1),)
    assert result.retrieved_evidence_ids == ("book:0f5ba253568e4836",)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"statusCode": 503}, "HTTP 503"),
        (
            {
                "statusCode": 200,
                "response": FakeBody(b'{"candidates": [], "tool_calls": []}'),
            },
            "invalid agent response",
        ),
    ],
)
def test_invoke_runtime_endpoint_rejects_invalid_responses(
    response: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeSmokeError, match=message):
        invoke_runtime_endpoint(
            FakeRuntimeClient(response),
            "runtime-arn",
            "stable",
            "Recommend a compiler project",
            "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
        )


def trace_message(
    *,
    session_id: str = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
    operation: str = "invoke_agent",
    scope: str = "strands.telemetry.tracer",
    cache_read_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> str:
    """Build one representative CloudWatch OpenTelemetry span record."""
    return json.dumps(
        {
            "resource": {
                "attributes": {
                    "cloud.resource_id": (
                        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/"
                        "example-runtime/runtime-endpoint/stable:6"
                    ),
                    "service.name": "praxis_dev_agent.stable",
                }
            },
            "scope": {"name": scope},
            "traceId": "6a83d54108313407510590e54dfc81d6",
            "spanId": f"span-{operation}",
            "attributes": {
                "gen_ai.usage.cache_read_input_tokens": cache_read_input_tokens,
                "gen_ai.usage.cache_write_input_tokens": cache_write_input_tokens,
                "gen_ai.operation.name": operation,
                "session.id": session_id,
            },
        }
    )


def test_parse_runtime_traces_requires_correlated_strands_agent_span() -> None:
    result = parse_runtime_traces(
        [
            trace_message(operation="chat"),
            trace_message(operation="invoke_agent"),
            trace_message(session_id="other-session"),
        ],
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime",
        "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
    )

    assert result is not None
    assert result.as_dict() == {
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "evaluation_scope_present": True,
        "operation_names": ["chat", "invoke_agent"],
        "scope_names": ["strands.telemetry.tracer"],
        "service_names": ["praxis_dev_agent.stable"],
        "session_correlated": True,
        "span_count": 2,
        "trace_count": 1,
    }


def test_parse_runtime_traces_rejects_transport_only_spans() -> None:
    result = parse_runtime_traces(
        [trace_message(scope="opentelemetry.instrumentation.botocore")],
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime",
        "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
    )

    assert result is None


def test_runtime_trace_log_group_targets_named_endpoint_span_stream() -> None:
    assert (
        runtime_trace_log_group(
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime",
            "stable",
        )
        == "/aws/bedrock-agentcore/runtimes/example-runtime-stable"
    )


def test_wait_for_runtime_traces_queries_endpoint_span_stream() -> None:
    class FakeLogsClient:
        request: dict[str, object] | None = None

        def filter_log_events(self, **kwargs: object) -> dict[str, object]:
            self.request = kwargs
            return {"events": [{"message": trace_message()}]}

    client = FakeLogsClient()
    result = wait_for_runtime_traces(
        client,
        "/aws/bedrock-agentcore/runtimes/example-runtime-stable",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime",
        "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
        1234,
        1,
    )

    assert result.as_dict()["evaluation_scope_present"] is True
    assert client.request == {
        "filterPattern": '"6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"',
        "logGroupName": "/aws/bedrock-agentcore/runtimes/example-runtime-stable",
        "logStreamNames": ["spans"],
        "startTime": 1234,
    }


def test_runtime_trace_reports_and_accepts_prompt_cache_read() -> None:
    result = RuntimeTraceResult(
        (RuntimeTraceSpan.model_validate_json(trace_message(cache_read_input_tokens=1_200)),)
    )

    assert result.as_dict()["cache_read_input_tokens"] == 1_200
