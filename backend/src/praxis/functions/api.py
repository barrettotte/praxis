"""Private AWS Lambda entry point for the Praxis application API."""

from functools import cache
from typing import cast
from uuid import uuid4

from pydantic import JsonValue

from praxis.api.correlation import response_correlation_id
from praxis.api.requests import ApiRequestError, CreateSessionRequest, validate_api_request
from praxis.api.responses import ApiErrorCode, error_response, success_response
from praxis.api.runtime import (
    ApiRuntimeError,
    CreateSessionData,
    RuntimeClient,
    create_runtime_client,
    invoke_runtime,
    load_runtime_settings,
)


@cache
def runtime_client() -> RuntimeClient:
    """Reuse the AgentCore client across warm Lambda invocations."""
    return create_runtime_client()


def create_session(goal: str, correlation_id: str) -> CreateSessionData:
    """Create one isolated Runtime session for a validated goal."""
    return invoke_runtime(
        runtime_client(),
        load_runtime_settings(),
        goal,
        str(uuid4()),
        correlation_id,
    )


def lambda_handler(event: object, context: object) -> dict[str, object]:
    """Validate one API Gateway request before dispatching application work."""
    fallback_correlation_id = response_correlation_id(event, context)
    try:
        request = validate_api_request(event)
    except ApiRequestError:
        return error_response(ApiErrorCode.INVALID_REQUEST, fallback_correlation_id)
    if request.route_key == "POST /v1/sessions":
        body = cast("CreateSessionRequest", request.body)
        try:
            session = create_session(body.goal, request.correlation_id)
        except ApiRuntimeError:
            return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
        return success_response(
            201,
            cast(
                "dict[str, JsonValue]",
                session.model_dump(mode="json", by_alias=True),
            ),
            request.correlation_id,
        )
    return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
