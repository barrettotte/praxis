"""Integration tests across the API handler and bounded Runtime adapter."""

import json
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from praxis.functions import api as api_function

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"


class FakeBody:
    """In-memory stand-in for the Runtime SDK response stream."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeRuntimeClient:
    """Capture an AgentCore invocation and return its configured result."""

    def __init__(self, response: dict[str, object] | Exception) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def candidate(number: int) -> dict[str, object]:
    """Return one schema-valid cited Runtime candidate."""
    return {
        "title": f"Candidate {number}",
        "summary": "Build a focused compiler project.",
        "rationale": "The evidence provides relevant implementation context.",
        "estimated_scope": "multi-week",
        "technologies": ["Python"],
        "first_milestone": "Implement one instruction-selection rule.",
        "evidence_citations": [
            {
                "evidence_id": "book:0f5ba253568e4836",
                "generated_connection": "The evidence supports this learning path.",
            }
        ],
    }


def runtime_response(payload: bytes | None = None) -> dict[str, object]:
    """Return a buffered response matching the AgentCore SDK boundary."""
    body = (
        payload
        or json.dumps(
            {
                "candidates": [candidate(number) for number in range(1, 4)],
                "evidence": [
                    {
                        "evidence_id": "book:0f5ba253568e4836",
                        "kind": "book",
                        "title": "Compiler Backend Development",
                        "author": None,
                        "year": 2025,
                        "category": "Compilers",
                        "tags": [],
                    }
                ],
                "memory": {"retrieved_count": 0},
                "tool_calls": [{"name": "search_catalog", "count": 1}],
            }
        ).encode()
    )
    return {
        "contentType": "application/json",
        "response": FakeBody(body),
        "runtimeSessionId": SESSION_ID,
        "statusCode": 200,
    }


def api_event(body: str) -> dict[str, object]:
    """Return the API Gateway v2 event used by the session route."""
    return {
        "version": "2.0",
        "routeKey": "POST /v1/sessions",
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "isBase64Encoded": False,
        "requestContext": {"requestId": "MqgCjHCKoAMEPLw="},
        "body": body,
    }


def configure_runtime(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeRuntimeClient,
) -> None:
    """Connect the real API adapter to a deterministic in-process Runtime client."""
    monkeypatch.setenv("PRAXIS_AGENT_RUNTIME_ARN", RUNTIME_ARN)
    monkeypatch.setenv("PRAXIS_AGENT_RUNTIME_QUALIFIER", "stable")
    monkeypatch.setenv("PRAXIS_API_ACTOR_ID", "praxis-single-user")
    monkeypatch.setattr(api_function, "runtime_client", lambda: client)
    monkeypatch.setattr(api_function, "uuid4", lambda: UUID(SESSION_ID))


def test_session_request_crosses_handler_and_runtime_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRuntimeClient(runtime_response())
    configure_runtime(monkeypatch, client)

    response = api_function.lambda_handler(
        api_event(json.dumps({"goal": "compiler"})),
        object(),
    )

    assert response["statusCode"] == 201
    assert response["headers"] == {
        "cache-control": "no-store",
        "content-type": "application/json",
        "x-correlation-id": CORRELATION_ID,
    }
    body = json.loads(str(response["body"]))
    assert body == {
        "data": {
            "sessionId": SESSION_ID,
            "candidates": [candidate(number) for number in range(1, 4)],
            "evidence": [
                {
                    "evidence_id": "book:0f5ba253568e4836",
                    "kind": "book",
                    "title": "Compiler Backend Development",
                    "author": None,
                    "year": 2025,
                    "category": "Compilers",
                    "tags": [],
                }
            ],
        }
    }
    assert client.requests == [
        {
            "accept": "application/json",
            "agentRuntimeArn": RUNTIME_ARN,
            "baggage": f"praxis.correlation_id={CORRELATION_ID}",
            "contentType": "application/json",
            "payload": b'{"actor_id":"praxis-single-user","prompt":"compiler"}',
            "qualifier": "stable",
            "runtimeSessionId": SESSION_ID,
        }
    ]


def test_invalid_request_stops_before_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRuntimeClient(runtime_response())
    configure_runtime(monkeypatch, client)

    response = api_function.lambda_handler(
        api_event(json.dumps({"unexpected": "do-not-reflect"})),
        object(),
    )

    assert response["statusCode"] == 400
    assert client.requests == []
    assert "do-not-reflect" not in json.dumps(response)


@pytest.mark.parametrize(
    "runtime_result",
    [
        ClientError(
            {
                "Error": {
                    "Code": "RuntimeClientError",
                    "Message": "sensitive model or tool failure",
                }
            },
            "InvokeAgentRuntime",
        ),
        runtime_response(b"sensitive malformed Runtime content"),
    ],
    ids=["dependency-error", "invalid-output"],
)
def test_runtime_failures_cross_as_safe_fixed_errors(
    monkeypatch: pytest.MonkeyPatch,
    runtime_result: dict[str, object] | Exception,
) -> None:
    client = FakeRuntimeClient(runtime_result)
    configure_runtime(monkeypatch, client)

    response = api_function.lambda_handler(
        api_event(json.dumps({"goal": "compiler"})),
        object(),
    )

    assert response["statusCode"] == 503
    assert json.loads(str(response["body"])) == {
        "error": {
            "code": "service_unavailable",
            "message": "Recommendation service is temporarily unavailable.",
        }
    }
    assert "sensitive" not in json.dumps(response)
