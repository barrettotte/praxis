"""Integration tests across the asynchronous API and Runtime worker boundaries."""

import json
from base64 import b64encode
from typing import cast
from uuid import UUID

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from praxis.api.jobs import RecommendationJob
from praxis.api.runtime import CreateSessionData, SelectCandidateData
from praxis.api.sessions import (
    AnySession,
    FailedSession,
    PendingSession,
    StoredBrief,
    StoredSession,
)
from praxis.functions import api as api_function
from praxis.functions import recommendation_worker

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/praxis-dev-recommendations"
EXPIRES_AT = 1_788_235_600
GOAL = "compiler"
ACTOR_ID = "7b9db85b-9448-4a41-9bb7-235a461429ae"
OTHER_ACTOR_ID = "945e3fcc-6522-4e07-920d-115a097df1c8"


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
        self.record: AnySession | None = None
        self.previous: dict[str, AnySession] = {}

    def start(self, session_id: str, actor_id: str, goal: str) -> PendingSession:
        if self.record is not None:
            self.previous[self.record.session_id] = self.record
        self.record = PendingSession(
            session_id=session_id,
            expires_at=EXPIRES_AT,
            goal=goal,
            actor_id=actor_id,
        )
        return self.record

    def complete(self, session: CreateSessionData, actor_id: str, goal: str) -> StoredSession:
        self.record = StoredSession(
            **session.model_dump(mode="python"),
            expires_at=EXPIRES_AT,
            goal=goal,
            actor_id=actor_id,
        )
        return self.record

    def complete_brief(
        self, selection: SelectCandidateData, actor_id: str, goal: str
    ) -> StoredBrief:
        self.record = StoredBrief(
            **selection.model_dump(mode="python"),
            actor_id=actor_id,
            goal=goal,
            expires_at=EXPIRES_AT,
        )
        return self.record

    def fail(self, session_id: str, actor_id: str) -> None:
        assert self.record is not None
        assert self.record.actor_id == actor_id
        self.record = FailedSession(
            session_id=session_id,
            expires_at=EXPIRES_AT,
            goal=self.record.goal,
            actor_id=actor_id,
        )

    def get_record(self, session_id: str, actor_id: str) -> AnySession | None:
        if (
            self.record is not None
            and self.record.session_id == session_id
            and self.record.actor_id == actor_id
        ):
            return self.record
        previous = self.previous.get(session_id)
        return previous if previous is not None and previous.actor_id == actor_id else None

    def get(self, session_id: str, actor_id: str) -> StoredSession | None:
        record = self.get_record(session_id, actor_id)
        return record if isinstance(record, StoredSession) else None


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


def api_event(
    route_key: str,
    *,
    body: str | None = None,
    actor_id: str = ACTOR_ID,
) -> dict[str, object]:
    """Return an authenticated API Gateway v2 event."""
    event: dict[str, object] = {
        "version": "2.0",
        "routeKey": route_key,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "isBase64Encoded": False,
        "requestContext": {
            "requestId": "MqgCjHCKoAMEPLw=",
            "authorizer": {"jwt": {"claims": {"sub": actor_id}}},
        },
    }
    if body is not None:
        event["body"] = body
    if "{sessionId}" in route_key:
        event["pathParameters"] = {"sessionId": SESSION_ID}
    if "{candidateId}" in route_key:
        event["pathParameters"] = {"candidateId": "candidate_1"}
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
    queued_job = RecommendationJob.model_validate_json(queue.message_body or "")
    assert queued_job.goal == "compiler"
    assert queued_job.actor_id == ACTOR_ID

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


@pytest.mark.parametrize("encoded", [False, True], ids=["json", "base64-json"])
@pytest.mark.parametrize(
    "secret",
    [
        "AKIA" + "A" * 16,
        "ASIA" + "B" * 16,
        "ghp_" + "c" * 36,
        "github_pat_" + "d" * 60,
        "sk-proj-" + "e" * 40,
        "-----BEGIN RSA PRIVATE KEY-----\nsynthetic\n-----END RSA PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzeW50aGV0aWMifQ.c3ludGhldGlj",
        "Authorization: Bearer synthetic-credential",
        '"password": "synthetic-credential"',
        "AWS_SECRET_ACCESS_KEY=synthetic-credential",
        "api_key = synthetic-credential",
    ],
)
def test_pasted_credentials_stop_before_storage_queue_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    secret: str,
    encoded: bool,
) -> None:
    client = FakeRuntimeClient(runtime_response())
    store, queue = configure_pipeline(monkeypatch, client)
    body = json.dumps({"goal": f"Help me build a project with {secret}"})
    event = api_event(
        "POST /v1/sessions", body=b64encode(body.encode()).decode() if encoded else body
    )
    event["isBase64Encoded"] = encoded

    response = api_function.lambda_handler(event, object())

    assert response["statusCode"] == 400
    assert json.loads(str(response["body"])) == {
        "error": {
            "code": "sensitive_input",
            "message": "Remove passwords, API keys, or tokens from your goal.",
        }
    }
    assert store.record is None
    assert queue.message_body is None
    assert client.requests == []
    captured = capsys.readouterr()
    assert secret not in json.dumps(response) + captured.out + captured.err + caplog.text


@pytest.mark.parametrize("fail_runtime", [False, True], ids=["success", "dependency-error"])
def test_authentication_material_stays_out_of_jobs_runtime_state_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    fail_runtime: bool,
) -> None:
    marker = "synthetic-credential-do-not-propagate"
    failure = ClientError(
        {"Error": {"Code": "RuntimeClientError", "Message": marker}}, "InvokeAgentRuntime"
    )
    client = FakeRuntimeClient(failure if fail_runtime else runtime_response())
    store, queue = configure_pipeline(monkeypatch, client)
    event = api_event("POST /v1/sessions", body=json.dumps({"goal": GOAL}))
    headers = cast("dict[str, str]", event["headers"])
    headers.update({"authorization": f"Bearer {marker}", "cookie": f"session={marker}"})
    event["requestContext"] = {
        "requestId": "MqgCjHCKoAMEPLw=",
        "authorizer": {"jwt": {"claims": {"sub": ACTOR_ID, "unused_claim": marker}}},
    }

    accepted = api_function.lambda_handler(event, object())
    assert accepted["statusCode"] == 202
    assert recommendation_worker.lambda_handler(sqs_event(queue), object()) == {"processed": 1}
    status = api_function.lambda_handler(api_event("GET /v1/sessions/{sessionId}"), object())

    assert len(client.requests) == 1
    assert json.loads(cast("bytes", client.requests[0]["payload"])) == {
        "prompt": GOAL,
    }
    assert store.record is not None
    captured = capsys.readouterr()
    surfaces = (
        queue.message_body or "",
        repr(client.requests),
        store.record.model_dump_json(),
        json.dumps([accepted, status]),
        captured.out,
        captured.err,
        caplog.text,
    )
    assert all(marker not in surface for surface in surfaces)


def test_foreign_actor_cannot_read_or_select_from_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRuntimeClient(runtime_response())
    _, queue = configure_pipeline(monkeypatch, client)
    api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"goal": "compiler"})),
        object(),
    )
    recommendation_worker.lambda_handler(sqs_event(queue), object())

    status = api_function.lambda_handler(
        api_event("GET /v1/sessions/{sessionId}", actor_id=OTHER_ACTOR_ID),
        object(),
    )
    selection = api_function.lambda_handler(
        api_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            actor_id=OTHER_ACTOR_ID,
        ),
        object(),
    )

    assert status["statusCode"] == 404
    assert selection["statusCode"] == 404
    assert status["body"] == selection["body"]
    assert "compiler" not in json.dumps([status, selection])
    assert len(client.requests) == 1


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
        ReadTimeoutError(endpoint_url="https://sensitive.example.com"),
        ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "sensitive throttle detail"}},
            "InvokeAgentRuntime",
        ),
    ],
    ids=["dependency-error", "invalid-output", "timeout", "throttled"],
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

    assert recommendation_worker.lambda_handler(sqs_event(queue), object()) == {"processed": 1}
    response = api_function.lambda_handler(
        api_event("GET /v1/sessions/{sessionId}"),
        object(),
    )

    assert response["statusCode"] == 200
    assert json.loads(str(response["body"])) == {
        "data": {"sessionId": SESSION_ID, "status": "failed"}
    }
    assert "sensitive" not in json.dumps(response)
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [
        ReadTimeoutError(endpoint_url="https://sensitive.example.com"),
        ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "sensitive throttle detail"}},
            "InvokeAgentRuntime",
        ),
    ],
    ids=["timeout", "throttled"],
)
def test_selection_failure_preserves_candidates_and_exposes_safe_job_failure(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    client = FakeRuntimeClient(runtime_response())
    store, queue = configure_pipeline(monkeypatch, client)
    api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"goal": GOAL})), object()
    )
    recommendation_worker.lambda_handler(sqs_event(queue), object())
    ready_record = store.record
    client.response = failure
    brief_id = "afdf7a75-4cd4-4e13-958c-2b7dcf27a112"
    monkeypatch.setattr(api_function, "uuid4", lambda: UUID(brief_id))

    response = api_function.lambda_handler(
        api_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
        ),
        object(),
    )

    assert response["statusCode"] == 202
    assert len(client.requests) == 1
    recommendation_worker.lambda_handler(sqs_event(queue), object())
    failed = store.get_record(brief_id, ACTOR_ID)
    assert isinstance(failed, FailedSession)
    assert store.get(SESSION_ID, ACTOR_ID) is ready_record
    assert len(client.requests) == 2
    recommendation_worker.lambda_handler(sqs_event(queue), object())
    assert len(client.requests) == 2


def test_brief_job_completes_and_repeated_delivery_does_not_invoke_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRuntimeClient(runtime_response())
    store, queue = configure_pipeline(monkeypatch, client)
    api_function.lambda_handler(
        api_event("POST /v1/sessions", body=json.dumps({"goal": GOAL})), object()
    )
    recommendation_worker.lambda_handler(sqs_event(queue), object())
    source = store.record
    brief_id = "afdf7a75-4cd4-4e13-958c-2b7dcf27a112"
    monkeypatch.setattr(api_function, "uuid4", lambda: UUID(brief_id))
    client.response = runtime_response(
        json.dumps(
            {
                "brief": {
                    "objective": "Build a compiler expression evaluator.",
                    "scope": "One expression type over a weekend.",
                    "deliverables": ["A tested expression evaluator."],
                    "milestones": [
                        {
                            "title": "Implement addition",
                            "deliverable": "An addition evaluator.",
                            "verification": "Run addition with 2 and 3 and assert 5.",
                        }
                    ],
                    "acceptance_criteria": [
                        {
                            "criterion": "Addition returns the expected integer.",
                            "verification": "Run the addition regression tests.",
                        }
                    ],
                }
            }
        ).encode()
    )
    client.response["runtimeSessionId"] = brief_id
    accepted = api_function.lambda_handler(
        api_event(
            "POST /v1/projects/{candidateId}/select", body=json.dumps({"sessionId": SESSION_ID})
        ),
        object(),
    )
    assert accepted["statusCode"] == 202
    assert len(client.requests) == 1
    delivery = sqs_event(queue)
    recommendation_worker.lambda_handler(delivery, object())
    assert isinstance(store.record, StoredBrief)
    assert store.record.candidate_id == "candidate_1"
    assert store.get(SESSION_ID, ACTOR_ID) is source
    assert store.get_record(brief_id, OTHER_ACTOR_ID) is None
    event = api_event("GET /v1/sessions/{sessionId}")
    event["pathParameters"] = {"sessionId": brief_id}
    response = api_function.lambda_handler(event, object())
    data = json.loads(str(response["body"]))["data"]
    assert data["status"] == "brief_ready"
    assert "goal" not in data
    assert "actor_id" not in data
    assert "expires_at" not in data
    recommendation_worker.lambda_handler(delivery, object())
    assert len(client.requests) == 2
