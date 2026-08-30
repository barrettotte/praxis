"""Tests for signed AgentCore Runtime smoke validation."""

import json
from pathlib import Path

import pytest

from praxis.agent.runtime_smoke import (
    RuntimeSmokeError,
    RuntimeSmokeResult,
    RuntimeToolCall,
    RuntimeTraceResult,
    RuntimeTraceSpan,
    SessionIsolationResult,
    invoke_runtime_endpoint,
    parse_runtime_traces,
    runtime_trace_log_group,
    verify_session_isolation,
    wait_for_runtime_traces,
    write_evidence,
    write_session_isolation_evidence,
    write_trace_evidence,
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


def valid_response() -> dict[str, object]:
    payload = {
        "candidates": candidate_set().model_dump(mode="json")["candidates"],
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
        "payload": b'{"prompt": "Recommend a compiler project"}',
        "qualifier": "stable",
        "runtimeSessionId": session_id,
    }
    assert result.candidates == candidate_set()
    assert result.tool_calls == (RuntimeToolCall(name="search_catalog", count=1),)


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


def test_write_evidence_omits_runtime_arn_and_session_id(tmp_path: Path) -> None:
    result = RuntimeSmokeResult(
        candidate_set(),
        (RuntimeToolCall(name="search_catalog", count=1),),
        "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
        "application/json",
    )

    evidence_path = write_evidence(tmp_path, "stable", "2", result)

    assert json.loads(evidence_path.read_text()) == {
        "all_candidates_cited": True,
        "authentication": "AWS_IAM",
        "candidate_count": 3,
        "client": "Boto3 AgentCore Runtime",
        "endpoint_qualifier": "stable",
        "endpoint_version": "2",
        "evidence_ids": ["book:0f5ba253568e4836"],
        "request_content_type": "application/json",
        "response_content_type": "application/json",
        "runtime_session_id_length": 36,
        "tool_calls": [{"count": 1, "name": "search_catalog"}],
    }


class SequentialRuntimeClient:
    """Return one configured Runtime response per invocation."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, object]] = []

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        return next(self.responses)


def response_for(evidence_id: str) -> dict[str, object]:
    payload = {
        "candidates": candidate_set(evidence_id).model_dump(mode="json")["candidates"],
        "tool_calls": [{"name": "search_catalog", "count": 1}],
    }
    return {
        "statusCode": 200,
        "contentType": "application/json",
        "response": FakeBody(json.dumps(payload).encode()),
    }


def test_verify_session_isolation_requires_disjoint_evidence() -> None:
    first_session_id = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
    second_session_id = "51f4a405-8835-411d-9821-5980d73f51f6"
    client = SequentialRuntimeClient(
        [
            response_for("book:0f5ba253568e4836"),
            response_for("museum:17ca91a13603360c"),
        ]
    )

    result = verify_session_isolation(
        client,
        "runtime-arn",
        "stable",
        "compiler",
        "commodore",
        (first_session_id, second_session_id),
    )

    assert result.as_dict()["sessions_distinct"] is True
    assert result.as_dict()["evidence_sets_disjoint"] is True
    assert [request["runtimeSessionId"] for request in client.requests] == [
        first_session_id,
        second_session_id,
    ]


def test_verify_session_isolation_rejects_overlapping_evidence() -> None:
    client = SequentialRuntimeClient(
        [
            response_for("book:0f5ba253568e4836"),
            response_for("book:0f5ba253568e4836"),
        ]
    )

    with pytest.raises(RuntimeSmokeError, match="overlapping evidence contexts"):
        verify_session_isolation(
            client,
            "runtime-arn",
            "stable",
            "compiler",
            "commodore",
            (
                "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
                "51f4a405-8835-411d-9821-5980d73f51f6",
            ),
        )


def test_write_session_isolation_evidence_omits_session_ids(tmp_path: Path) -> None:
    result = SessionIsolationResult(
        first=RuntimeSmokeResult(
            candidate_set("book:0f5ba253568e4836"),
            (RuntimeToolCall(name="search_catalog", count=1),),
            "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
            "application/json",
        ),
        second=RuntimeSmokeResult(
            candidate_set("museum:17ca91a13603360c"),
            (RuntimeToolCall(name="search_catalog", count=1),),
            "51f4a405-8835-411d-9821-5980d73f51f6",
            "application/json",
        ),
    )

    evidence_path = write_session_isolation_evidence(tmp_path, "stable", "6", result)
    capture = json.loads(evidence_path.read_text())

    assert capture["sessions_distinct"] is True
    assert capture["evidence_sets_disjoint"] is True
    assert capture["session_id_lengths"] == [36, 36]
    assert "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4" not in evidence_path.read_text()


def trace_message(
    *,
    session_id: str = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
    operation: str = "invoke_agent",
    scope: str = "strands.telemetry.tracer",
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


def test_write_trace_evidence_omits_span_trace_session_and_resource_ids(tmp_path: Path) -> None:
    span = RuntimeTraceSpan.model_validate_json(trace_message())
    result = RuntimeTraceResult((span,))

    evidence_path = write_trace_evidence(tmp_path, "stable", "6", result)
    capture = json.loads(evidence_path.read_text())

    assert capture["evaluation_scope_present"] is True
    assert capture["endpoint_version"] == "6"
    assert capture["span_count"] == 1
    assert "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4" not in evidence_path.read_text()
    assert "123456789012" not in evidence_path.read_text()
