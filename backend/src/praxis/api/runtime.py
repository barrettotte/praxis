"""Invoke AgentCore Runtime through a bounded API application adapter."""

import json
import os
from collections.abc import Mapping
from typing import Annotated, Protocol, cast
from urllib.parse import quote

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from praxis.domain import ProjectCandidate

JSON_CONTENT_TYPE = "application/json"


class ApiRuntimeError(RuntimeError):
    """Raised when Runtime configuration, invocation, or output is invalid."""


class RuntimeClient(Protocol):
    """AgentCore data-plane method used by the API Lambda."""

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]: ...


class ResponseBody(Protocol):
    """Buffered read surface returned by the AgentCore SDK."""

    def read(self) -> bytes: ...


class ApiRuntimeSettings(BaseModel):
    """Validated deployment-owned Runtime invocation settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    runtime_arn: Annotated[str, Field(min_length=1)]
    qualifier: Annotated[
        str,
        Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$"),
    ]
    actor_id: Annotated[
        str,
        Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_/-]{0,254}$"),
    ]


class _RuntimeMemoryUsage(BaseModel):
    """Internal Memory metadata required from the Runtime response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    retrieved_count: Annotated[int, Field(ge=0)]


class _RuntimeToolCall(BaseModel):
    """Internal bounded tool-call metadata required from the Runtime response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: Annotated[str, Field(min_length=1)]
    count: Annotated[int, Field(ge=1)]


class _RuntimeOutput(BaseModel):
    """Strict buffered output accepted from the deployed Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidates: Annotated[list[ProjectCandidate], Field(min_length=3, max_length=3)]
    memory: _RuntimeMemoryUsage
    tool_calls: Annotated[list[_RuntimeToolCall], Field(min_length=1, max_length=4)]


class CreateSessionData(BaseModel):
    """Public data returned after creating a Runtime-backed session."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    session_id: Annotated[
        str,
        Field(
            alias="sessionId",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        ),
    ]
    candidates: Annotated[list[ProjectCandidate], Field(min_length=3, max_length=3)]


def load_runtime_settings(
    environment: Mapping[str, str] | None = None,
) -> ApiRuntimeSettings:
    """Load deployment-owned Runtime settings without accepting client values."""
    values = environment if environment is not None else os.environ
    try:
        return ApiRuntimeSettings(
            runtime_arn=values.get("PRAXIS_AGENT_RUNTIME_ARN", ""),
            qualifier=values.get("PRAXIS_AGENT_RUNTIME_QUALIFIER", ""),
            actor_id=values.get("PRAXIS_API_ACTOR_ID", ""),
        )
    except ValidationError as error:
        raise ApiRuntimeError("invalid Runtime configuration") from error


def create_runtime_client() -> RuntimeClient:
    """Create an AgentCore client bounded below the API Gateway deadline."""
    try:
        return cast(
            "RuntimeClient",
            Session().client(  # pyright: ignore[reportUnknownMemberType]
                "bedrock-agentcore",
                config=Config(
                    connect_timeout=3,
                    read_timeout=25,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            ),
        )
    except BotoCoreError as error:
        raise ApiRuntimeError("Runtime client initialization failed") from error


def invoke_runtime(
    client: RuntimeClient,
    settings: ApiRuntimeSettings,
    goal: str,
    session_id: str,
    correlation_id: str,
) -> CreateSessionData:
    """Invoke one Runtime session and return only validated public data."""
    payload = json.dumps(
        {"actor_id": settings.actor_id, "prompt": goal.strip()},
        separators=(",", ":"),
    ).encode()
    try:
        response = client.invoke_agent_runtime(
            accept=JSON_CONTENT_TYPE,
            agentRuntimeArn=settings.runtime_arn,
            baggage=f"praxis.correlation_id={quote(correlation_id, safe='')}",
            contentType=JSON_CONTENT_TYPE,
            payload=payload,
            qualifier=settings.qualifier,
            runtimeSessionId=session_id,
        )
    except (BotoCoreError, ClientError) as error:
        raise ApiRuntimeError("Runtime invocation failed") from error

    if response.get("statusCode") != 200:
        raise ApiRuntimeError("Runtime invocation failed")
    content_type = response.get("contentType")
    response_body = response.get("response")
    if (
        not isinstance(content_type, str)
        or content_type.partition(";")[0].strip().casefold() != JSON_CONTENT_TYPE
        or response.get("runtimeSessionId") != session_id
        or response_body is None
        or not hasattr(response_body, "read")
    ):
        raise ApiRuntimeError("Runtime returned an invalid response")

    try:
        output = _RuntimeOutput.model_validate_json(cast("ResponseBody", response_body).read())
        return CreateSessionData(session_id=session_id, candidates=output.candidates)
    except (BotoCoreError, ValidationError) as error:
        raise ApiRuntimeError("Runtime returned an invalid response") from error
