"""Tests for consistent application API response envelopes."""

import json

import pytest
from pydantic import ValidationError

from praxis.api.responses import ApiErrorCode, error_response, success_response


def test_builds_success_response_envelope() -> None:
    response = success_response(201, {"sessionId": "session-1"})

    assert response == {
        "statusCode": 201,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
        },
        "body": '{"data":{"sessionId":"session-1"}}',
        "isBase64Encoded": False,
    }


@pytest.mark.parametrize(
    ("code", "status_code", "message"),
    [
        (ApiErrorCode.INVALID_REQUEST, 400, "Invalid request."),
        (
            ApiErrorCode.SERVICE_UNAVAILABLE,
            503,
            "Application API routes are unavailable.",
        ),
    ],
)
def test_builds_safe_error_response_envelope(
    code: ApiErrorCode,
    status_code: int,
    message: str,
) -> None:
    response = error_response(code)

    assert response["statusCode"] == status_code
    assert json.loads(str(response["body"])) == {"error": {"code": code.value, "message": message}}


def test_rejects_non_json_success_data() -> None:
    with pytest.raises(ValidationError):
        success_response(200, {"unsupported": object()})  # type: ignore[dict-item]


def test_rejects_non_success_status_for_success_envelope() -> None:
    with pytest.raises(ValueError, match="success status"):
        success_response(400, {})


def test_returns_independent_transport_objects() -> None:
    first = error_response(ApiErrorCode.INVALID_REQUEST)
    second = error_response(ApiErrorCode.INVALID_REQUEST)

    assert first is not second
    assert first["headers"] is not second["headers"]
