"""Select and validate correlation IDs at the public API boundary."""

import re
from collections.abc import Mapping
from typing import cast
from uuid import uuid4

_CLIENT_CORRELATION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_TRUSTED_REQUEST_ID = re.compile(r"^[A-Za-z0-9._=-]{1,128}$")


class CorrelationIdError(ValueError):
    """Raised when request metadata cannot supply a valid correlation ID."""


def _mapping(value: object) -> Mapping[object, object]:
    if isinstance(value, Mapping):
        return cast("Mapping[object, object]", value)
    return {}


def _client_correlation_id(event: object) -> str | None:
    headers = _mapping(_mapping(event).get("headers"))
    values = [
        value
        for name, value in headers.items()
        if isinstance(name, str) and name.casefold() == "x-correlation-id"
    ]
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], str):
        raise CorrelationIdError("invalid correlation ID header")
    correlation_id = values[0]
    if _CLIENT_CORRELATION_ID.fullmatch(correlation_id) is None:
        raise CorrelationIdError("invalid correlation ID header")
    return correlation_id


def _gateway_request_id(event: object) -> str | None:
    request_context = _mapping(_mapping(event).get("requestContext"))
    request_id = request_context.get("requestId")
    if isinstance(request_id, str) and _TRUSTED_REQUEST_ID.fullmatch(request_id):
        return request_id
    return None


def validate_response_correlation_id(correlation_id: str) -> str:
    """Reject values that are unsafe to place in an HTTP response header."""
    if _TRUSTED_REQUEST_ID.fullmatch(correlation_id) is None:
        raise ValueError("invalid response correlation ID")
    return correlation_id


def correlation_id_from_event(event: object) -> str:
    """Use a valid client UUID or the trusted API Gateway request ID."""
    client_id = _client_correlation_id(event)
    if client_id is not None:
        return client_id
    gateway_id = _gateway_request_id(event)
    if gateway_id is None:
        raise CorrelationIdError("invalid correlation ID metadata")
    return gateway_id


def response_correlation_id(event: object, context: object) -> str:
    """Choose a safe response ID even when public request validation fails."""
    try:
        return correlation_id_from_event(event)
    except CorrelationIdError:
        gateway_id = _gateway_request_id(event)
        if gateway_id is not None:
            return gateway_id
        lambda_id = getattr(context, "aws_request_id", None)
        if isinstance(lambda_id, str) and _TRUSTED_REQUEST_ID.fullmatch(lambda_id):
            return lambda_id
        return str(uuid4())
