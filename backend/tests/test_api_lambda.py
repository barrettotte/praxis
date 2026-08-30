"""Tests for application API request validation and the Lambda entry point."""

import json
from base64 import b64encode

import pytest

from praxis.api.requests import (
    ApiRequestError,
    CreateSessionRequest,
    SelectCandidateRequest,
    SessionMessageRequest,
    validate_api_request,
)
from praxis.api.runtime import ApiRuntimeError, CreateSessionData
from praxis.domain import EvidenceCitation, ProjectCandidate
from praxis.functions import api as api_function

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
GATEWAY_REQUEST_ID = "MqgCjHCKoAMEPLw="


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


def test_validates_create_session_request() -> None:
    request = validate_api_request(
        http_event("POST /v1/sessions", body=json.dumps({"goal": " Learn Rust "}))
    )

    assert request.route_key == "POST /v1/sessions"
    assert request.correlation_id == GATEWAY_REQUEST_ID
    assert request.path_parameters == {}
    assert request.body == CreateSessionRequest(goal="Learn Rust")


def test_validates_base64_encoded_message_request() -> None:
    encoded_body = b64encode(json.dumps({"message": "Continue"}).encode()).decode()

    request = validate_api_request(
        http_event(
            "POST /v1/sessions/{sessionId}/messages",
            body=encoded_body,
            path_parameters={"sessionId": SESSION_ID},
            is_base64_encoded=True,
            content_type="application/json; charset=utf-8",
        )
    )

    assert request.path_parameters == {"sessionId": SESSION_ID}
    assert request.body == SessionMessageRequest(message="Continue")


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
            "POST /v1/sessions/{sessionId}/messages",
            body=json.dumps({"message": "valid"}),
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
        "invalid-base64",
        "invalid-correlation-id",
    ],
)
def test_rejects_invalid_requests(event: object) -> None:
    with pytest.raises(ApiRequestError, match="invalid API request"):
        validate_api_request(event)


def test_api_lambda_invokes_runtime_for_valid_create_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "do-not-reflect"
    observed: list[tuple[str, str]] = []

    def create_session(goal: str, correlation_id: str) -> CreateSessionData:
        observed.append((goal, correlation_id))
        return CreateSessionData(
            session_id=SESSION_ID,
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
                            evidence_id="book:0f5ba253568e4836",
                            generated_connection="The evidence supports this learning path.",
                        )
                    ],
                )
                for number in range(1, 4)
            ],
        )

    monkeypatch.setattr(api_function, "create_session", create_session)

    response = api_function.lambda_handler(
        http_event(
            "POST /v1/sessions",
            body=json.dumps({"goal": marker}),
            correlation_id=CORRELATION_ID,
        ),
        object(),
    )

    assert response["statusCode"] == 201
    assert response["headers"] == {
        "cache-control": "no-store",
        "content-type": "application/json",
        "x-correlation-id": CORRELATION_ID,
    }
    assert json.loads(str(response["body"])) == {
        "data": {
            "sessionId": SESSION_ID,
            "candidates": [
                {
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
                for number in range(1, 4)
            ],
        }
    }
    assert response["isBase64Encoded"] is False
    assert observed == [(marker, CORRELATION_ID)]


def test_api_lambda_returns_safe_unavailable_when_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_session(_goal: str, _correlation_id: str) -> CreateSessionData:
        raise ApiRuntimeError("sensitive dependency failure")

    monkeypatch.setattr(api_function, "create_session", fail_create_session)

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
            '"message":"Application API routes are unavailable."}}'
        ),
        "isBase64Encoded": False,
    }
    assert "sensitive dependency failure" not in json.dumps(response)


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


def test_api_lambda_returns_independent_response_objects() -> None:
    event = http_event(
        "GET /v1/sessions/{sessionId}",
        path_parameters={"sessionId": SESSION_ID},
    )

    first = api_function.lambda_handler(event, object())
    second = api_function.lambda_handler(event, object())

    assert first is not second
    assert first["headers"] is not second["headers"]
