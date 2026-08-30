"""Tests for safe API correlation-ID selection."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from praxis.api.correlation import (
    CorrelationIdError,
    correlation_id_from_event,
    response_correlation_id,
)

CLIENT_CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
GATEWAY_REQUEST_ID = "MqgCjHCKoAMEPLw="
LAMBDA_REQUEST_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"


def test_prefers_valid_client_correlation_id() -> None:
    event = {
        "headers": {"X-Correlation-ID": CLIENT_CORRELATION_ID},
        "requestContext": {"requestId": GATEWAY_REQUEST_ID},
    }

    assert correlation_id_from_event(event) == CLIENT_CORRELATION_ID


def test_uses_gateway_request_id_without_client_header() -> None:
    event = {"headers": {}, "requestContext": {"requestId": GATEWAY_REQUEST_ID}}

    assert correlation_id_from_event(event) == GATEWAY_REQUEST_ID


def test_rejects_invalid_client_correlation_id() -> None:
    event = {
        "headers": {"x-correlation-id": "not-a-uuid"},
        "requestContext": {"requestId": GATEWAY_REQUEST_ID},
    }

    with pytest.raises(CorrelationIdError, match="invalid correlation ID"):
        correlation_id_from_event(event)


def test_response_uses_gateway_id_when_client_id_is_invalid() -> None:
    event = {
        "headers": {"x-correlation-id": "not-a-uuid"},
        "requestContext": {"requestId": GATEWAY_REQUEST_ID},
    }

    assert response_correlation_id(event, object()) == GATEWAY_REQUEST_ID


def test_response_falls_back_to_lambda_request_id() -> None:
    context = SimpleNamespace(aws_request_id=LAMBDA_REQUEST_ID)

    assert response_correlation_id({}, context) == LAMBDA_REQUEST_ID


def test_response_generates_uuid_without_request_metadata() -> None:
    correlation_id = response_correlation_id({}, object())

    assert str(UUID(correlation_id, version=4)) == correlation_id
