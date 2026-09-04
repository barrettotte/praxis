"""Strict request contracts for API Gateway HTTP API events."""

from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from praxis.api.correlation import CorrelationIdError, correlation_id_from_event
from praxis.api.prompt_safety import contains_likely_secret

MAX_API_BODY_BYTES = 16 * 1024
MAX_API_TEXT_CHARACTERS = 4_000
_MAX_BASE64_BODY_CHARACTERS = ((MAX_API_BODY_BYTES + 2) // 3) * 4

type ApiRoute = Literal[
    "GET /v1/sessions/{sessionId}",
    "POST /v1/projects/{candidateId}/select",
    "POST /v1/sessions",
]
type SessionId = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]
type CandidateId = Annotated[
    str,
    Field(pattern=r"^candidate_[1-3]$"),
]
type ActorId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$",
    ),
]


class ApiRequestError(ValueError):
    """Raised when an API Gateway event violates the public request contract."""


class ApiPayloadTooLargeError(ApiRequestError):
    """Raised when a request body exceeds the application payload limit."""


class ApiSensitiveInputError(ApiRequestError):
    """Raised when a goal appears to contain pasted credentials."""


class RequestModel(BaseModel):
    """Apply strict validation to public JSON request bodies."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class CreateSessionRequest(RequestModel):
    """A goal that starts a planning session."""

    goal: Annotated[str, Field(min_length=1, max_length=MAX_API_TEXT_CHARACTERS)]


class SelectCandidateRequest(RequestModel):
    """The session that owns a selected candidate."""

    session_id: SessionId = Field(alias="sessionId")


type ApiRequestBody = CreateSessionRequest | SelectCandidateRequest


class _HttpApiEvent(BaseModel):
    """API Gateway v2 event fields needed at the application boundary."""

    model_config = ConfigDict(extra="ignore", strict=True)

    route_key: ApiRoute = Field(alias="routeKey")
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    body: str | None = None
    is_base64_encoded: bool = Field(default=False, alias="isBase64Encoded")
    path_parameters: dict[str, str] | None = Field(default=None, alias="pathParameters")
    query_parameters: dict[str, str] | None = Field(
        default=None,
        alias="queryStringParameters",
    )
    request_context: "_RequestContext" = Field(alias="requestContext")


class _JwtClaims(BaseModel):
    """Validated identity claims supplied by the API Gateway JWT authorizer."""

    model_config = ConfigDict(extra="ignore", strict=True)

    sub: ActorId


class _JwtAuthorizer(BaseModel):
    """JWT authorizer context forwarded to the Lambda integration."""

    model_config = ConfigDict(extra="ignore", strict=True)

    claims: _JwtClaims


class _AuthorizerContext(BaseModel):
    """Supported API Gateway authorizer result shape."""

    model_config = ConfigDict(extra="ignore", strict=True)

    jwt: _JwtAuthorizer


class _RequestContext(BaseModel):
    """Authenticated API Gateway request context used by the application."""

    model_config = ConfigDict(extra="ignore", strict=True)

    authorizer: _AuthorizerContext


@dataclass(frozen=True)
class ValidatedApiRequest:
    """A route-aware request safe for application handlers to consume."""

    route_key: ApiRoute
    path_parameters: dict[str, str]
    body: ApiRequestBody | None
    correlation_id: str
    actor_id: str


_SESSION_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(SessionId)
_CANDIDATE_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(CandidateId)
_BODY_MODELS: dict[str, type[RequestModel]] = {
    "POST /v1/projects/{candidateId}/select": SelectCandidateRequest,
    "POST /v1/sessions": CreateSessionRequest,
}


def _has_json_content_type(headers: dict[str, str]) -> bool:
    for name, value in headers.items():
        media_type = value.partition(";")[0].strip().casefold()
        if name.casefold() == "content-type" and media_type == "application/json":
            return True
    return False


def _decode_body(event: _HttpApiEvent) -> str:
    if event.body is None:
        raise ValueError("request body is required")
    if not event.is_base64_encoded:
        if len(event.body.encode("utf-8")) > MAX_API_BODY_BYTES:
            raise ApiPayloadTooLargeError(f"API request payload exceeds {MAX_API_BODY_BYTES} bytes")
        return event.body
    # Reject clearly oversized encoded input before allocating its decoded form.
    if len(event.body) > _MAX_BASE64_BODY_CHARACTERS:
        raise ApiPayloadTooLargeError(f"API request payload exceeds {MAX_API_BODY_BYTES} bytes")
    try:
        decoded_body = b64decode(event.body, validate=True)
    except Base64Error as error:
        raise ValueError("request body is not valid base64-encoded UTF-8") from error
    if len(decoded_body) > MAX_API_BODY_BYTES:
        raise ApiPayloadTooLargeError(f"API request payload exceeds {MAX_API_BODY_BYTES} bytes")
    try:
        return decoded_body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("request body is not valid base64-encoded UTF-8") from error


def _validate_path_parameters(event: _HttpApiEvent) -> dict[str, str]:
    path_parameters = event.path_parameters or {}
    if event.route_key == "GET /v1/sessions/{sessionId}":
        if set(path_parameters) != {"sessionId"}:
            raise ValueError("sessionId path parameter is required")
        return {
            "sessionId": _SESSION_ID_ADAPTER.validate_python(
                path_parameters["sessionId"],
                strict=True,
            )
        }
    if event.route_key == "POST /v1/projects/{candidateId}/select":
        if set(path_parameters) != {"candidateId"}:
            raise ValueError("candidateId path parameter is required")
        return {
            "candidateId": _CANDIDATE_ID_ADAPTER.validate_python(
                path_parameters["candidateId"],
                strict=True,
            )
        }
    if path_parameters:
        raise ValueError("route does not accept path parameters")
    return {}


def _validate_event(event: _HttpApiEvent, correlation_id: str) -> ValidatedApiRequest:
    if event.query_parameters:
        raise ValueError("route does not accept query parameters")
    path_parameters = _validate_path_parameters(event)
    if event.route_key == "GET /v1/sessions/{sessionId}":
        if event.body is not None or event.is_base64_encoded:
            raise ValueError("route does not accept a request body")
        return ValidatedApiRequest(
            event.route_key,
            path_parameters,
            None,
            correlation_id,
            event.request_context.authorizer.jwt.claims.sub,
        )
    if not _has_json_content_type(event.headers):
        raise ValueError("content-type must be application/json")
    body = cast(
        "ApiRequestBody", _BODY_MODELS[event.route_key].model_validate_json(_decode_body(event))
    )
    if isinstance(body, CreateSessionRequest) and contains_likely_secret(body.goal):
        raise ApiSensitiveInputError("goal appears to contain credentials")
    return ValidatedApiRequest(
        event.route_key,
        path_parameters,
        body,
        correlation_id,
        event.request_context.authorizer.jwt.claims.sub,
    )


def validate_api_request(event: object) -> ValidatedApiRequest:
    """Validate an API Gateway v2 event without exposing failure details."""
    try:
        correlation_id = correlation_id_from_event(event)
        return _validate_event(_HttpApiEvent.model_validate(event), correlation_id)
    except (ApiPayloadTooLargeError, ApiSensitiveInputError):
        raise
    except (CorrelationIdError, KeyError, ValidationError, ValueError) as error:
        raise ApiRequestError("invalid API request") from error
