"""Consistent JSON envelopes for API Gateway Lambda proxy responses."""

from enum import StrEnum
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from praxis.api.correlation import validate_response_correlation_id


class ResponseModel(BaseModel):
    """Apply strict validation to public API response bodies."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class ApiSuccessResponse(ResponseModel):
    """Wrap successful application data under a stable top-level field."""

    data: dict[str, JsonValue]


class ApiErrorCode(StrEnum):
    """Stable machine-readable codes exposed by the application boundary."""

    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    SENSITIVE_INPUT = "sensitive_input"
    SERVICE_UNAVAILABLE = "service_unavailable"


class ApiError(ResponseModel):
    """A safe machine-readable and human-readable error."""

    code: ApiErrorCode
    message: str


class ApiErrorResponse(ResponseModel):
    """Wrap an API error under a stable top-level field."""

    error: ApiError


class _LambdaProxyResponse(ResponseModel):
    """Fields returned from Lambda to API Gateway HTTP APIs."""

    status_code: Annotated[int, Field(alias="statusCode", ge=100, le=599)]
    headers: dict[str, str]
    body: str
    is_base64_encoded: Literal[False] = Field(alias="isBase64Encoded")


_ERROR_DEFINITIONS: dict[ApiErrorCode, tuple[int, str]] = {
    ApiErrorCode.INVALID_REQUEST: (400, "Invalid request."),
    ApiErrorCode.NOT_FOUND: (404, "Requested recommendation session was not found."),
    ApiErrorCode.PAYLOAD_TOO_LARGE: (413, "Request payload is too large."),
    ApiErrorCode.SENSITIVE_INPUT: (400, "Remove passwords, API keys, or tokens from your goal."),
    ApiErrorCode.SERVICE_UNAVAILABLE: (
        503,
        "Recommendation service is temporarily unavailable.",
    ),
}


def _json_response(
    status_code: int,
    payload: ResponseModel,
    correlation_id: str,
) -> dict[str, object]:
    response = _LambdaProxyResponse(
        status_code=status_code,
        headers={
            "cache-control": "no-store",
            "content-type": "application/json",
            "x-correlation-id": validate_response_correlation_id(correlation_id),
        },
        body=payload.model_dump_json(by_alias=True),
        isBase64Encoded=False,
    )
    return cast("dict[str, object]", response.model_dump(by_alias=True))


def success_response(
    status_code: int,
    data: dict[str, JsonValue],
    correlation_id: str,
) -> dict[str, object]:
    """Build a validated, non-cacheable success response."""
    if not 200 <= status_code <= 299:
        raise ValueError("success status must be between 200 and 299")
    return _json_response(status_code, ApiSuccessResponse(data=data), correlation_id)


def error_response(code: ApiErrorCode, correlation_id: str) -> dict[str, object]:
    """Build a fixed safe response for a stable error code."""
    status_code, message = _ERROR_DEFINITIONS[code]
    return _json_response(
        status_code,
        ApiErrorResponse(error=ApiError(code=code, message=message)),
        correlation_id,
    )
