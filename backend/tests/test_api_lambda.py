"""Tests for application API request validation and the Lambda entry point."""

import json
from base64 import b64encode

import pytest

from praxis.api.jobs import ApiJobError
from praxis.api.requests import (
    MAX_API_BODY_BYTES,
    MAX_API_TEXT_CHARACTERS,
    ApiPayloadTooLargeError,
    ApiRequestError,
    CreateSessionRequest,
    SelectCandidateRequest,
    validate_api_request,
)
from praxis.api.runtime import (
    CreateSessionData,
    SelectCandidateData,
    SessionCandidate,
)
from praxis.api.sessions import (
    ApiSessionError,
    ApiSessionNotFoundError,
    FailedSession,
    PendingSession,
    StoredSession,
)
from praxis.domain import EvidenceCitation
from praxis.domain.briefs import (
    ProjectAcceptanceCriterion,
    ProjectBrief,
    ProjectMilestone,
    ProjectRisk,
)
from praxis.functions import api as api_function
from praxis.tools.contracts import BookEvidence

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
GATEWAY_REQUEST_ID = "MqgCjHCKoAMEPLw="
GOAL = "Learn compiler backends over a weekend"


def http_event(
    route_key: str,
    *,
    body: str | None = None,
    path_parameters: dict[str, str] | None = None,
    query_parameters: dict[str, str] | None = None,
    is_base64_encoded: bool = False,
    content_type: str = "application/json",
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Build the API Gateway v2 fields consumed by the request validator."""
    event: dict[str, object] = {
        "version": "2.0",
        "routeKey": route_key,
        "headers": {"content-type": content_type},
        "isBase64Encoded": is_base64_encoded,
        "requestContext": {"requestId": GATEWAY_REQUEST_ID},
    }
    if correlation_id is not None:
        headers = event["headers"]
        assert isinstance(headers, dict)
        headers["x-correlation-id"] = correlation_id
    if body is not None:
        event["body"] = body
    if path_parameters is not None:
        event["pathParameters"] = path_parameters
    if query_parameters is not None:
        event["queryStringParameters"] = query_parameters
    return event


def create_session_data() -> CreateSessionData:
    """Return one complete recommendation session fixture."""
    return CreateSessionData(
        session_id=SESSION_ID,
        candidates=[
            SessionCandidate(
                candidate_id=f"candidate_{number}",
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides relevant implementation context.",
                estimated_scope="multi-week",
                technologies=["Python"],
                first_milestone="Implement one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0f5ba253568e4836",
                        generated_connection="The evidence supports this learning path.",
                    )
                ],
            )
            for number in range(1, 4)
        ],
        evidence=[
            BookEvidence(
                evidence_id="book:0f5ba253568e4836",
                kind="book",
                title="Compiler Backend Development",
                author=None,
                year=2025,
                category="Compilers",
                tags=[],
            )
        ],
    )


def test_validates_create_session_request() -> None:
    request = validate_api_request(
        http_event("POST /v1/sessions", body=json.dumps({"goal": " Learn Rust "}))
    )

    assert request.route_key == "POST /v1/sessions"
    assert request.correlation_id == GATEWAY_REQUEST_ID
    assert request.path_parameters == {}
    assert request.body == CreateSessionRequest(goal="Learn Rust")


def test_validates_base64_encoded_create_session_request() -> None:
    encoded_body = b64encode(json.dumps({"goal": "Learn Rust"}).encode()).decode()

    request = validate_api_request(
        http_event(
            "POST /v1/sessions",
            body=encoded_body,
            is_base64_encoded=True,
            content_type="application/json; charset=utf-8",
        )
    )

    assert request.path_parameters == {}
    assert request.body == CreateSessionRequest(goal="Learn Rust")


def test_validates_client_correlation_id() -> None:
    request = validate_api_request(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "Learn Rust"}),
            correlation_id=CORRELATION_ID,
        )
    )

    assert request.correlation_id == CORRELATION_ID


def test_validates_get_session_request_without_body() -> None:
    request = validate_api_request(
        http_event(
            "GET /v1/sessions/{sessionId}",
            path_parameters={"sessionId": SESSION_ID},
        )
    )

    assert request.path_parameters == {"sessionId": SESSION_ID}
    assert request.body is None


def test_validates_candidate_selection_request() -> None:
    request = validate_api_request(
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            path_parameters={"candidateId": "candidate_1"},
        )
    )

    assert request.path_parameters == {"candidateId": "candidate_1"}
    assert request.body == SelectCandidateRequest(sessionId=SESSION_ID)


@pytest.mark.parametrize("is_base64_encoded", [False, True], ids=["raw", "base64"])
def test_accepts_request_at_body_size_limit(is_base64_encoded: bool) -> None:
    decoded_body = json.dumps({"sessionId": SESSION_ID})
    decoded_body += " " * (MAX_API_BODY_BYTES - len(decoded_body.encode("utf-8")))
    body = b64encode(decoded_body.encode("utf-8")).decode() if is_base64_encoded else decoded_body

    request = validate_api_request(
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=body,
            path_parameters={"candidateId": "candidate_1"},
            is_base64_encoded=is_base64_encoded,
        )
    )

    assert len(decoded_body.encode("utf-8")) == MAX_API_BODY_BYTES
    assert request.body == SelectCandidateRequest(sessionId=SESSION_ID)


@pytest.mark.parametrize("is_base64_encoded", [False, True], ids=["raw", "base64"])
def test_rejects_request_above_body_size_limit(is_base64_encoded: bool) -> None:
    decoded_body = "\u00e9" * ((MAX_API_BODY_BYTES // 2) + 1)
    body = b64encode(decoded_body.encode("utf-8")).decode() if is_base64_encoded else decoded_body

    with pytest.raises(ApiPayloadTooLargeError, match="payload exceeds"):
        validate_api_request(
            http_event(
                "POST /v1/sessions",
                body=body,
                is_base64_encoded=is_base64_encoded,
            )
        )


def test_rejects_goal_above_character_limit() -> None:
    with pytest.raises(ApiRequestError, match="invalid API request"):
        validate_api_request(
            http_event(
                "POST /v1/sessions",
                body=json.dumps({"goal": "a" * (MAX_API_TEXT_CHARACTERS + 1)}),
            )
        )


@pytest.mark.parametrize(
    "event",
    [
        {"routeKey": "POST /not-a-route"},
        http_event("POST /v1/sessions", body="not-json"),
        http_event("POST /v1/sessions", body="[]"),
        http_event("POST /v1/sessions", body="{}"),
        http_event("POST /v1/sessions", body=json.dumps({"goal": "   "})),
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "valid", "unexpected": True}),
        ),
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "valid"}),
            content_type="text/plain",
        ),
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "valid"}),
            query_parameters={"debug": "true"},
        ),
        http_event(
            "GET /v1/sessions/{sessionId}",
            path_parameters={"sessionId": "not-a-session"},
        ),
        http_event(
            "GET /v1/sessions/{sessionId}",
            body="{}",
            path_parameters={"sessionId": SESSION_ID},
        ),
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            path_parameters={"candidateId": "not/a/candidate"},
        ),
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            path_parameters={"candidateId": "candidate_4"},
        ),
        http_event(
            "POST /v1/sessions",
            body="not-base64",
            is_base64_encoded=True,
        ),
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "valid"}),
            correlation_id="not-a-uuid",
        ),
    ],
    ids=[
        "unknown-route",
        "malformed-json",
        "non-object-json",
        "missing-field",
        "blank-field",
        "unknown-field",
        "wrong-content-type",
        "query-parameter",
        "invalid-session-id",
        "get-body",
        "invalid-candidate-id",
        "unknown-candidate-id",
        "invalid-base64",
        "invalid-correlation-id",
    ],
)
def test_rejects_invalid_requests(event: object) -> None:
    with pytest.raises(ApiRequestError, match="invalid API request"):
        validate_api_request(event)


def test_api_lambda_accepts_and_queues_valid_create_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "do-not-reflect"
    observed: list[tuple[str, str]] = []

    def start_session(goal: str, correlation_id: str) -> PendingSession:
        observed.append((goal, correlation_id))
        return PendingSession(
            session_id=SESSION_ID,
            expires_at=1_788_235_600,
            goal=marker,
        )

    monkeypatch.setattr(api_function, "start_session", start_session)

    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": marker}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 202
    assert response["headers"] == {
        "cache-control": "no-store",
        "content-type": "application/json",
        "x-correlation-id": CORRELATION_ID,
    }
    assert json.loads(str(response["body"])) == {
        "data": {
            "sessionId": SESSION_ID,
            "status": "pending",
        }
    }
    assert response["isBase64Encoded"] is False
    assert observed == [(marker, CORRELATION_ID)]


@pytest.mark.parametrize(
    "session",
    [
        PendingSession(session_id=SESSION_ID, expires_at=1_788_235_600, goal=GOAL),
        FailedSession(session_id=SESSION_ID, expires_at=1_788_235_600, goal=GOAL),
    ],
)
def test_api_lambda_returns_non_ready_session_status(
    monkeypatch: pytest.MonkeyPatch,
    session: PendingSession | FailedSession,
) -> None:
    def get_session(_session_id: str) -> PendingSession | FailedSession:
        return session

    monkeypatch.setattr(api_function, "get_session", get_session)

    response = api_function.lambda_handler(
        http_event(
            "GET /v1/sessions/{sessionId}",
            path_parameters={"sessionId": SESSION_ID},
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 200
    assert json.loads(str(response["body"])) == {
        "data": {"sessionId": SESSION_ID, "status": session.status}
    }


def test_api_lambda_returns_ready_session_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    session = StoredSession(
        **create_session_data().model_dump(mode="python"),
        expires_at=1_788_235_600,
        goal=GOAL,
    )

    def get_session(_session_id: str) -> StoredSession:
        return session

    monkeypatch.setattr(api_function, "get_session", get_session)

    response = api_function.lambda_handler(
        http_event(
            "GET /v1/sessions/{sessionId}",
            path_parameters={"sessionId": SESSION_ID},
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 200
    payload = json.loads(str(response["body"]))["data"]
    assert payload["status"] == "ready"
    assert len(payload["candidates"]) == 3
    assert len(payload["evidence"]) == 1
    assert "goal" not in payload


def test_api_lambda_returns_generated_brief_for_session_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = SessionCandidate(
        candidate_id="candidate_2",
        title="Candidate 2",
        summary="Build a focused compiler project.",
        rationale="The evidence provides relevant implementation context.",
        estimated_scope="multi-week",
        technologies=["Python"],
        first_milestone="Implement one instruction-selection rule.",
        evidence_citations=[
            EvidenceCitation(
                evidence_id="book:0f5ba253568e4836",
                generated_connection="The evidence supports this learning path.",
            )
        ],
    )
    evidence = BookEvidence(
        evidence_id="book:0f5ba253568e4836",
        kind="book",
        title="Compiler Backend Development",
        author=None,
        year=2025,
        category="Compilers",
        tags=[],
    )
    brief = ProjectBrief(
        objective="Build a small compiler backend.",
        scope="Implement one expression-lowering path.",
        technical_approach=[
            "Define a JSON expression model and validate sample inputs.",
            "Lower expressions into target instructions with Python.",
            "Execute the instructions and compare their numeric result.",
        ],
        assumptions=[
            "Python and a local test runner are available.",
            "One expression form is enough for the exercise.",
        ],
        out_of_scope=[
            "Register allocation is outside this project.",
            "Multiple target architectures are outside this project.",
        ],
        deliverables=[
            "A documented input representation for expressions.",
            "A tested instruction selector with example output.",
        ],
        milestones=[
            ProjectMilestone(
                title=f"Milestone {number}",
                deliverable="A concrete implementation artifact.",
                verification="An automated check validates the artifact.",
            )
            for number in range(1, 4)
        ],
        risks=[
            ProjectRisk(risk=f"Risk {number}", mitigation="Use a bounded fallback.")
            for number in range(1, 3)
        ],
        acceptance_criteria=[
            ProjectAcceptanceCriterion(
                criterion=f"Criterion {number} has a measurable result.",
                verification="An automated test records the expected result.",
            )
            for number in range(1, 4)
        ],
    )
    observed: list[tuple[str, str, str]] = []

    def select_candidate(
        session_id: str,
        candidate_id: str,
        correlation_id: str,
    ) -> SelectCandidateData:
        observed.append((session_id, candidate_id, correlation_id))
        return SelectCandidateData(
            session_id=session_id,
            candidate_id=candidate_id,
            candidate=selected,
            brief=brief,
            evidence=[evidence],
        )

    monkeypatch.setattr(api_function, "select_candidate", select_candidate)
    response = api_function.lambda_handler(
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            path_parameters={"candidateId": "candidate_2"},
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 200
    payload = json.loads(str(response["body"]))["data"]
    assert payload["sessionId"] == SESSION_ID
    assert payload["candidateId"] == "candidate_2"
    assert payload["candidate"]["title"] == "Candidate 2"
    assert payload["brief"]["acceptance_criteria"][0] == {
        "criterion": "Criterion 1 has a measurable result.",
        "verification": "An automated test records the expected result.",
    }
    assert observed == [(SESSION_ID, "candidate_2", CORRELATION_ID)]


def test_api_lambda_returns_not_found_for_expired_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def select_candidate(_session_id: str, _candidate_id: str, _correlation_id: str) -> None:
        raise ApiSessionNotFoundError("sensitive session detail")

    monkeypatch.setattr(api_function, "select_candidate", select_candidate)
    response = api_function.lambda_handler(
        http_event(
            "POST /v1/projects/{candidateId}/select",
            body=json.dumps({"sessionId": SESSION_ID}),
            path_parameters={"candidateId": "candidate_1"},
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 404
    assert json.loads(str(response["body"])) == {
        "error": {
            "code": "not_found",
            "message": "Requested recommendation session was not found.",
        }
    }


def test_api_lambda_returns_safe_unavailable_when_job_cannot_be_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_detail = "sensitive queue detail"

    def fail_start_session(_goal: str, _correlation_id: str) -> PendingSession:
        raise ApiJobError(sensitive_detail)

    monkeypatch.setattr(api_function, "start_session", fail_start_session)

    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "compiler"}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response == {
        "statusCode": 503,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "body": (
            '{"error":{"code":"service_unavailable",'
            '"message":"Recommendation service is temporarily unavailable."}}'
        ),
        "isBase64Encoded": False,
    }
    assert sensitive_detail not in json.dumps(response)
    assert "queue" not in json.dumps(response)


def test_api_lambda_returns_safe_unavailable_when_session_cannot_be_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start_session(_goal: str, _correlation_id: str) -> PendingSession:
        raise ApiSessionError("sensitive DynamoDB detail")

    monkeypatch.setattr(api_function, "start_session", fail_start_session)
    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": "compiler"}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 503
    assert "sensitive DynamoDB detail" not in json.dumps(response)


def test_api_lambda_returns_safe_bad_request_for_invalid_input() -> None:
    marker = "do-not-reflect"

    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"unexpected": marker}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 400
    assert response["headers"] == {
        "cache-control": "no-store",
        "content-type": "application/json",
        "x-correlation-id": CORRELATION_ID,
    }
    assert response["body"] == ('{"error":{"code":"invalid_request","message":"Invalid request."}}')
    assert marker not in json.dumps(response)


def test_api_lambda_rejects_oversized_payload_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "do-not-reflect"

    def unexpected_start_session(_goal: str, _correlation_id: str) -> PendingSession:
        pytest.fail("oversized request queued work")

    monkeypatch.setattr(api_function, "start_session", unexpected_start_session)
    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": marker, "padding": "x" * MAX_API_BODY_BYTES}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response == {
        "statusCode": 413,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "body": (
            '{"error":{"code":"payload_too_large","message":"Request payload is too large."}}'
        ),
        "isBase64Encoded": False,
    }
    assert marker not in json.dumps(response)


def test_api_lambda_returns_independent_response_objects() -> None:
    event = http_event(
        "GET /v1/sessions/{sessionId}",
        path_parameters={"sessionId": SESSION_ID},
    )

    first = api_function.lambda_handler(event, object())
    second = api_function.lambda_handler(event, object())

    assert first is not second
    assert first["headers"] is not second["headers"]
