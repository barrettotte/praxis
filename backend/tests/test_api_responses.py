"""Tests for consistent application API response envelopes."""

import json

import pytest
from pydantic import ValidationError

from praxis.api.responses import ApiErrorCode, error_response, success_response

CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"


def test_builds_success_response_envelope() -> None:
    response = success_response(201, {"sessionId": "session-1"}, CORRELATION_ID)

    assert response == {
        "statusCode": 201,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
            "x-correlation-id": CORRELATION_ID,
        },
        "body": '{"data":{"sessionId":"session-1"}}',
        "isBase64Encoded": False,
    }


@pytest.mark.parametrize(
    ("code", "status_code", "message"),
    [
        (ApiErrorCode.INVALID_REQUEST, 400, "Invalid request."),
        (
            ApiErrorCode.SENSITIVE_INPUT,
            400,
            "Remove passwords, API keys, or tokens from your goal.",
        ),
        (
            ApiErrorCode.NOT_FOUND,
            404,
            "Requested recommendation session was not found.",
        ),
        (
            ApiErrorCode.PAYLOAD_TOO_LARGE,
            413,
            "Request payload is too large.",
        ),
        (
            ApiErrorCode.SERVICE_UNAVAILABLE,
            503,
            "Recommendation service is temporarily unavailable.",
        ),
    ],
)
def test_builds_safe_error_response_envelope(
    code: ApiErrorCode,
    status_code: int,
    message: str,
) -> None:
    response = error_response(code, CORRELATION_ID)

    assert response["statusCode"] == status_code
    assert json.loads(str(response["body"])) == {"error": {"code": code.value, "message": message}}


def test_rejects_non_json_success_data() -> None:
    with pytest.raises(ValidationError):
        success_response(200, {"unsupported": object()}, CORRELATION_ID)  # type: ignore[dict-item]


def test_rejects_non_success_status_for_success_envelope() -> None:
    with pytest.raises(ValueError, match="success status"):
        success_response(400, {}, CORRELATION_ID)


def test_rejects_invalid_response_correlation_id() -> None:
    with pytest.raises(ValueError, match="invalid response correlation ID"):
        error_response(ApiErrorCode.INVALID_REQUEST, "contains whitespace")


def test_returns_independent_transport_objects() -> None:
    first = error_response(ApiErrorCode.INVALID_REQUEST, CORRELATION_ID)
    second = error_response(ApiErrorCode.INVALID_REQUEST, CORRELATION_ID)

    assert first is not second
    assert first["headers"] is not second["headers"]
