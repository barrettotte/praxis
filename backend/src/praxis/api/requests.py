"""Strict request contracts for API Gateway HTTP API events."""

from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

type ApiRoute = Literal[
    "GET /v1/sessions/{sessionId}",
    "POST /v1/projects/{candidateId}/select",
    "POST /v1/sessions",
    "POST /v1/sessions/{sessionId}/messages",
]
type SessionId = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]
type CandidateId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]


class ApiRequestError(ValueError):
    """Raised when an API Gateway event violates the public request contract."""


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

    goal: Annotated[str, Field(min_length=1)]


class SessionMessageRequest(RequestModel):
    """A follow-up message within an existing session."""

    message: Annotated[str, Field(min_length=1)]


class SelectCandidateRequest(RequestModel):
    """The session that owns a selected candidate."""

    session_id: SessionId = Field(alias="sessionId")


type ApiRequestBody = CreateSessionRequest | SessionMessageRequest | SelectCandidateRequest


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


@dataclass(frozen=True)
class ValidatedApiRequest:
    """A route-aware request safe for application handlers to consume."""

    route_key: ApiRoute
    path_parameters: dict[str, str]
    body: ApiRequestBody | None


_SESSION_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(SessionId)
_CANDIDATE_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(CandidateId)
_BODY_MODELS: dict[str, type[RequestModel]] = {
    "POST /v1/projects/{candidateId}/select": SelectCandidateRequest,
    "POST /v1/sessions": CreateSessionRequest,
    "POST /v1/sessions/{sessionId}/messages": SessionMessageRequest,
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
        return event.body
    try:
        return b64decode(event.body, validate=True).decode("utf-8")
    except (Base64Error, UnicodeDecodeError) as error:
        raise ValueError("request body is not valid base64-encoded UTF-8") from error


def _validate_path_parameters(event: _HttpApiEvent) -> dict[str, str]:
    path_parameters = event.path_parameters or {}
    if event.route_key in {
        "GET /v1/sessions/{sessionId}",
        "POST /v1/sessions/{sessionId}/messages",
    }:
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


def _validate_event(event: _HttpApiEvent) -> ValidatedApiRequest:
    if event.query_parameters:
        raise ValueError("route does not accept query parameters")
    path_parameters = _validate_path_parameters(event)
    if event.route_key == "GET /v1/sessions/{sessionId}":
        if event.body is not None or event.is_base64_encoded:
            raise ValueError("route does not accept a request body")
        return ValidatedApiRequest(event.route_key, path_parameters, None)
    if not _has_json_content_type(event.headers):
        raise ValueError("content-type must be application/json")
    body = cast(
        "ApiRequestBody", _BODY_MODELS[event.route_key].model_validate_json(_decode_body(event))
    )
    return ValidatedApiRequest(event.route_key, path_parameters, body)


def validate_api_request(event: object) -> ValidatedApiRequest:
    """Validate an API Gateway v2 event without exposing failure details."""
    try:
        return _validate_event(_HttpApiEvent.model_validate(event))
    except (KeyError, ValidationError, ValueError) as error:
        raise ApiRequestError("invalid API request") from error
