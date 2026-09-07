"""Invoke AgentCore Runtime through a bounded API application adapter."""

import json
import os
from collections.abc import Mapping
from typing import Annotated, Protocol, Self, cast
from urllib.parse import quote

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from praxis.domain import ProjectCandidate
from praxis.domain.briefs import ProjectBrief
from praxis.tools.contracts import Evidence

JSON_CONTENT_TYPE = "application/json"
WORKER_RUNTIME_READ_TIMEOUT_SECONDS = 90


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


class _RuntimeToolCall(BaseModel):
    """Internal bounded tool-call metadata required from the Runtime response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: Annotated[str, Field(min_length=1)]
    count: Annotated[int, Field(ge=1)]


class _RuntimeOutput(BaseModel):
    """Strict buffered output accepted from the deployed Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidates: Annotated[list[ProjectCandidate], Field(min_length=3, max_length=3)]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=3)]
    tool_calls: Annotated[list[_RuntimeToolCall], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def require_resolved_citations(self) -> Self:
        """Require unique fact records for every candidate citation."""
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Runtime evidence IDs must be unique")
        cited_ids = {
            citation.evidence_id
            for candidate in self.candidates
            for citation in candidate.evidence_citations
        }
        if not cited_ids <= set(evidence_ids):
            raise ValueError("Runtime citations must resolve to returned evidence")
        return self


class _RuntimeBriefOutput(BaseModel):
    """Strict project-brief output accepted from the deployed Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    brief: ProjectBrief


class SessionCandidate(ProjectCandidate):
    """A generated candidate with an application-assigned session identifier."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    candidate_id: Annotated[
        str,
        Field(alias="candidateId", pattern=r"^candidate_[1-3]$"),
    ]


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
    candidates: Annotated[list[SessionCandidate], Field(min_length=3, max_length=3)]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=3)]


class SelectCandidateData(BaseModel):
    """Public data returned after expanding one server-selected candidate."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    session_id: Annotated[str, Field(alias="sessionId", pattern=r"^[0-9a-f-]{36}$")]
    candidate_id: Annotated[str, Field(alias="candidateId", pattern=r"^candidate_[1-3]$")]
    candidate: SessionCandidate
    brief: ProjectBrief
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def require_selected_candidate_evidence(self) -> Self:
        """Require response identity and citations to match the selected session candidate."""
        if self.candidate.candidate_id != self.candidate_id:
            raise ValueError("selected candidate ID does not match")
        cited_ids = {item.evidence_id for item in self.candidate.evidence_citations}
        if not cited_ids <= {item.evidence_id for item in self.evidence}:
            raise ValueError("selected candidate evidence is unavailable")
        return self


def _invoke_runtime_payload(
    client: RuntimeClient,
    settings: ApiRuntimeSettings,
    payload: dict[str, object],
    session_id: str,
    correlation_id: str,
) -> bytes:
    """Invoke Runtime once and return a validated buffered JSON payload."""
    encoded_payload = json.dumps(payload, separators=(",", ":")).encode()
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    # Forward only standard trace identity, not vendor state or arbitrary baggage.
    trace_headers = {"traceParent": carrier["traceparent"]} if "traceparent" in carrier else {}
    if "traceparent" in carrier:
        # AgentCore's AWS tracing boundary also consumes the X-Ray representation.
        # Both headers must describe the same parent and preserve its sampling decision.
        _, trace_id, span_id, flags = carrier["traceparent"].split("-")
        trace_headers["traceId"] = (
            f"Root=1-{trace_id[:8]}-{trace_id[8:]};Parent={span_id};Sampled={int(flags, 16) & 1}"
        )
    try:
        response = client.invoke_agent_runtime(
            accept=JSON_CONTENT_TYPE,
            agentRuntimeArn=settings.runtime_arn,
            baggage=f"praxis.correlation_id={quote(correlation_id, safe='')}",
            contentType=JSON_CONTENT_TYPE,
            payload=encoded_payload,
            qualifier=settings.qualifier,
            runtimeSessionId=session_id,
            **trace_headers,
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
        return cast("ResponseBody", response_body).read()
    except BotoCoreError as error:
        raise ApiRuntimeError("Runtime returned an invalid response") from error


def load_runtime_settings(
    environment: Mapping[str, str] | None = None,
) -> ApiRuntimeSettings:
    """Load deployment-owned Runtime settings without accepting client values."""
    values = environment if environment is not None else os.environ
    try:
        return ApiRuntimeSettings(
            runtime_arn=values.get("PRAXIS_AGENT_RUNTIME_ARN", ""),
            qualifier=values.get("PRAXIS_AGENT_RUNTIME_QUALIFIER", ""),
        )
    except ValidationError as error:
        raise ApiRuntimeError("invalid Runtime configuration") from error


def _create_runtime_client(read_timeout_seconds: int) -> RuntimeClient:
    """Create an AgentCore client with one bounded invocation attempt."""
    try:
        return cast(
            "RuntimeClient",
            Session().client(  # pyright: ignore[reportUnknownMemberType]
                "bedrock-agentcore",
                config=Config(
                    connect_timeout=3,
                    read_timeout=read_timeout_seconds,
                    retries={"mode": "standard", "total_max_attempts": 1},
                ),
            ),
        )
    except BotoCoreError as error:
        raise ApiRuntimeError("Runtime client initialization failed") from error


def create_worker_runtime_client() -> RuntimeClient:
    """Create an AgentCore client bounded below the worker Lambda deadline."""
    return _create_runtime_client(WORKER_RUNTIME_READ_TIMEOUT_SECONDS)


def invoke_runtime(
    client: RuntimeClient,
    settings: ApiRuntimeSettings,
    goal: str,
    session_id: str,
    correlation_id: str,
) -> CreateSessionData:
    """Invoke one Runtime session and return only validated public data."""
    try:
        output = _RuntimeOutput.model_validate_json(
            _invoke_runtime_payload(
                client,
                settings,
                {"prompt": goal.strip()},
                session_id,
                correlation_id,
            )
        )
        cited_ids = {
            citation.evidence_id
            for candidate in output.candidates
            for citation in candidate.evidence_citations
        }
        public_evidence = [item for item in output.evidence if item.evidence_id in cited_ids]
        return CreateSessionData(
            session_id=session_id,
            candidates=[
                SessionCandidate(
                    candidate_id=f"candidate_{index}",
                    **candidate.model_dump(mode="python"),
                )
                for index, candidate in enumerate(output.candidates, start=1)
            ],
            evidence=public_evidence,
        )
    except ValidationError as error:
        raise ApiRuntimeError("Runtime returned an invalid response") from error


def invoke_project_brief_runtime(
    client: RuntimeClient,
    settings: ApiRuntimeSettings,
    session_id: str,
    goal: str,
    candidate: SessionCandidate,
    evidence: list[Evidence],
    correlation_id: str,
) -> SelectCandidateData:
    """Invoke Runtime with one server-selected candidate and its resolved evidence."""
    try:
        output = _RuntimeBriefOutput.model_validate_json(
            _invoke_runtime_payload(
                client,
                settings,
                {
                    "operation": "create_project_brief",
                    "goal": goal.strip(),
                    "candidate": candidate.model_dump(mode="json", exclude={"candidate_id"}),
                    "evidence": [item.model_dump(mode="json") for item in evidence],
                },
                session_id,
                correlation_id,
            )
        )
        return SelectCandidateData(
            session_id=session_id,
            candidate_id=candidate.candidate_id,
            candidate=candidate,
            brief=output.brief,
            evidence=evidence,
        )
    except ValidationError as error:
        raise ApiRuntimeError("Runtime returned an invalid response") from error
