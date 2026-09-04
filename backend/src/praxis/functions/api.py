"""Private AWS Lambda entry point for the Praxis application API."""

from functools import cache
from typing import cast
from uuid import uuid4

from pydantic import JsonValue

from praxis.api.correlation import response_correlation_id
from praxis.api.jobs import (
    ApiJobError,
    QueueClient,
    RecommendationJob,
    create_queue_client,
    enqueue_job,
    load_job_queue_url,
)
from praxis.api.requests import (
    ApiPayloadTooLargeError,
    ApiRequestError,
    CreateSessionRequest,
    SelectCandidateRequest,
    validate_api_request,
)
from praxis.api.responses import ApiErrorCode, error_response, success_response
from praxis.api.runtime import (
    ApiRuntimeError,
    RuntimeClient,
    SelectCandidateData,
    create_runtime_client,
    invoke_project_brief_runtime,
    load_runtime_settings,
)
from praxis.api.sessions import (
    AnySession,
    ApiSessionError,
    ApiSessionNotFoundError,
    PendingSession,
    create_session_store,
)


@cache
def runtime_client() -> RuntimeClient:
    """Reuse the AgentCore client across warm Lambda invocations."""
    return create_runtime_client()


@cache
def queue_client() -> QueueClient:
    """Reuse the bounded SQS client across warm Lambda invocations."""
    return create_queue_client()


def start_session(actor_id: str, goal: str, correlation_id: str) -> PendingSession:
    """Persist and queue one asynchronous recommendation session."""
    session_id = str(uuid4())
    store = create_session_store()
    pending = store.start(session_id, actor_id, goal)
    try:
        enqueue_job(
            queue_client(),
            load_job_queue_url(),
            RecommendationJob(
                session_id=session_id,
                goal=goal,
                correlation_id=correlation_id,
                actor_id=actor_id,
            ),
        )
    except ApiJobError:
        store.fail(session_id, actor_id)
        raise
    return pending


def get_session(session_id: str, actor_id: str) -> AnySession:
    """Return one unexpired asynchronous session state."""
    session = create_session_store().get_record(session_id, actor_id)
    if session is None:
        raise ApiSessionNotFoundError("recommendation session was not found")
    return session


def _public_session_data(session: AnySession) -> dict[str, JsonValue]:
    """Remove persistence metadata from one public session status response."""
    return cast(
        "dict[str, JsonValue]",
        session.model_dump(
            mode="json",
            by_alias=True,
            exclude={"actor_id", "expires_at", "goal"},
        ),
    )


def select_candidate(
    session_id: str,
    candidate_id: str,
    correlation_id: str,
    actor_id: str,
) -> SelectCandidateData:
    """Resolve one session-owned candidate and generate its project brief."""
    session = create_session_store().get(session_id, actor_id)
    if session is None:
        raise ApiSessionNotFoundError("recommendation session was not found")
    candidate = session.selected_candidate(candidate_id)
    if candidate is None:
        raise ApiSessionNotFoundError("recommendation candidate was not found")
    evidence = session.evidence_for(candidate)
    if not evidence:
        raise ApiSessionError("recommendation candidate evidence is unavailable")
    return invoke_project_brief_runtime(
        runtime_client(),
        load_runtime_settings(),
        session_id,
        session.goal,
        candidate,
        evidence,
        correlation_id,
    )


def lambda_handler(event: object, context: object) -> dict[str, object]:
    """Validate one API Gateway request before dispatching application work."""
    fallback_correlation_id = response_correlation_id(event, context)
    try:
        request = validate_api_request(event)
    except ApiPayloadTooLargeError:
        return error_response(ApiErrorCode.PAYLOAD_TOO_LARGE, fallback_correlation_id)
    except ApiRequestError:
        return error_response(ApiErrorCode.INVALID_REQUEST, fallback_correlation_id)
    if request.route_key == "POST /v1/sessions":
        body = cast("CreateSessionRequest", request.body)
        try:
            session = start_session(request.actor_id, body.goal, request.correlation_id)
        except (ApiJobError, ApiSessionError):
            return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
        return success_response(
            202,
            _public_session_data(session),
            request.correlation_id,
        )
    if request.route_key == "GET /v1/sessions/{sessionId}":
        try:
            session = get_session(request.path_parameters["sessionId"], request.actor_id)
        except ApiSessionNotFoundError:
            return error_response(ApiErrorCode.NOT_FOUND, request.correlation_id)
        except ApiSessionError:
            return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
        return success_response(200, _public_session_data(session), request.correlation_id)
    if request.route_key == "POST /v1/projects/{candidateId}/select":
        body = cast("SelectCandidateRequest", request.body)
        try:
            selection = select_candidate(
                body.session_id,
                request.path_parameters["candidateId"],
                request.correlation_id,
                request.actor_id,
            )
        except ApiSessionNotFoundError:
            return error_response(ApiErrorCode.NOT_FOUND, request.correlation_id)
        except (ApiRuntimeError, ApiSessionError):
            return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
        return success_response(
            200,
            cast(
                "dict[str, JsonValue]",
                selection.model_dump(mode="json", by_alias=True),
            ),
            request.correlation_id,
        )
    return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
