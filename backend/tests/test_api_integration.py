"""Integration tests across the asynchronous API and Runtime worker boundaries."""

import json
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from praxis.api.jobs import RecommendationJob
from praxis.api.runtime import CreateSessionData
from praxis.api.sessions import FailedSession, PendingSession, StoredSession
from praxis.functions import api as api_function
from praxis.functions import recommendation_worker

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/praxis-dev-recommendations"
EXPIRES_AT = 1_788_235_600
GOAL = "compiler"


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


class FakeQueueClient:
    """Capture the private SQS work item produced by the API."""

    def __init__(self) -> None:
        self.message_body: str | None = None

    def send_message(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["QueueUrl"] == QUEUE_URL
        self.message_body = str(kwargs["MessageBody"])
        return {"MessageId": "message-id"}


class FakeSessionStore:
    """Keep one session state across API and worker calls."""

    def __init__(self) -> None:
        self.record: PendingSession | FailedSession | StoredSession | None = None

    def start(self, session_id: str, goal: str) -> PendingSession:
        self.record = PendingSession(session_id=session_id, expires_at=EXPIRES_AT, goal=goal)
        return self.record

    def complete(self, session: CreateSessionData, goal: str) -> StoredSession:
        self.record = StoredSession(
            **session.model_dump(mode="python"),
            expires_at=EXPIRES_AT,
            goal=goal,
        )
        return self.record

    def fail(self, session_id: str) -> None:
        assert self.record is not None
        self.record = FailedSession(
            session_id=session_id,
            expires_at=EXPIRES_AT,
            goal=self.record.goal,
        )

    def get_record(self, session_id: str) -> PendingSession | FailedSession | StoredSession | None:
        if self.record is not None and self.record.session_id == session_id:
            return self.record
        return None


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


def api_event(route_key: str, *, body: str | None = None) -> dict[str, object]:
    """Return an authenticated API Gateway v2 event."""
    event: dict[str, object] = {
        "version": "2.0",
        "routeKey": route_key,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "isBase64Encoded": False,
        "requestContext": {"requestId": "MqgCjHCKoAMEPLw="},
    }
    if body is not None:
        event["body"] = body
    if "{sessionId}" in route_key:
        event["pathParameters"] = {"sessionId": SESSION_ID}
    return event


def configure_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    runtime_client: FakeRuntimeClient,
) -> tuple[FakeSessionStore, FakeQueueClient]:
    """Connect API and worker adapters through deterministic in-process fakes."""
    store = FakeSessionStore()
    queue = FakeQueueClient()
    monkeypatch.setenv("PRAXIS_AGENT_RUNTIME_ARN", RUNTIME_ARN)
    monkeypatch.setenv("PRAXIS_AGENT_RUNTIME_QUALIFIER", "stable")
    monkeypatch.setenv("PRAXIS_API_ACTOR_ID", "praxis-single-user")
    monkeypatch.setenv("PRAXIS_RECOMMENDATION_QUEUE_URL", QUEUE_URL)
    monkeypatch.setattr(api_function, "uuid4", lambda: UUID(SESSION_ID))
    monkeypatch.setattr(api_function, "create_session_store", lambda: store)
    monkeypatch.setattr(api_function, "queue_client", lambda: queue)
    monkeypatch.setattr(recommendation_worker, "create_session_store", lambda: store)
    monkeypatch.setattr(recommendation_worker, "runtime_client", lambda: runtime_client)
    return store, queue


def sqs_event(queue: FakeQueueClient) -> dict[str, object]:
    assert queue.message_body is not None
    return {"Records": [{"body": queue.message_body, "eventSource": "aws:sqs"}]}


def test_session_crosses_api_queue_worker_runtime_and_status_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRuntimeClient(runtime_response())
    _, queue = configure_pipeline(monkeypatch, client)

    accepted = api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"goal": "compiler"})),
        object(),
    )
    assert accepted["statusCode"] == 202
    assert json.loads(str(accepted["body"])) == {
        "data": {"sessionId": SESSION_ID, "status": "pending"}
    }
    assert RecommendationJob.model_validate_json(queue.message_body or "").goal == "compiler"

    assert recommendation_worker.lambda_handler(sqs_event(queue), object()) == {"processed": 1}
    ready = api_function.lambda_handler(
        api_event("GET /v1/sessions/{sessionId}"),
        object(),
    )

    assert ready["statusCode"] == 200
    payload = json.loads(str(ready["body"]))["data"]
    assert payload["status"] == "ready"
    assert "goal" not in payload
    assert len(payload["candidates"]) == 3
    assert len(payload["evidence"]) == 1
    assert client.requests[0]["runtimeSessionId"] == SESSION_ID


def test_invalid_request_stops_before_queue_and_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRuntimeClient(runtime_response())
    _, queue = configure_pipeline(monkeypatch, client)

    response = api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"unexpected": "do-not-reflect"})),
        object(),
    )

    assert response["statusCode"] == 400
    assert queue.message_body is None
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
def test_runtime_failures_become_safe_failed_session_state(
    monkeypatch: pytest.MonkeyPatch,
    runtime_result: dict[str, object] | Exception,
) -> None:
    client = FakeRuntimeClient(runtime_result)
    _, queue = configure_pipeline(monkeypatch, client)
    api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"goal": "compiler"})),
        object(),
    )

    recommendation_worker.lambda_handler(sqs_event(queue), object())
    response = api_function.lambda_handler(
        api_event("GET /v1/sessions/{sessionId}"),
        object(),
    )

    assert response["statusCode"] == 200
    assert json.loads(str(response["body"])) == {
        "data": {"sessionId": SESSION_ID, "status": "failed"}
    }
    assert "sensitive" not in json.dumps(response)
