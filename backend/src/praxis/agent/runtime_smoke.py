"""Signed smoke check for the deployed AgentCore Runtime endpoint."""

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol, cast
from uuid import uuid4

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from praxis.domain import ProjectCandidateSet
from praxis.tools.contracts import Evidence

DEFAULT_PROMPT = "compiler"
MINIMUM_SESSION_ID_LENGTH = 33
JSON_CONTENT_TYPE = "application/json"
JSON_OBJECT = TypeAdapter(dict[str, object])


class RuntimeClient(Protocol):
    """AgentCore data-plane method used by the smoke check."""

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]: ...


class LogsClient(Protocol):
    """CloudWatch Logs method used to verify exported Runtime spans."""

    def filter_log_events(self, **kwargs: object) -> dict[str, object]: ...


class ResponseBody(Protocol):
    """Streaming response surface returned by botocore."""

    def read(self) -> bytes: ...


class RuntimeToolCall(BaseModel):
    """Validated tool-call count returned by the hosted agent."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1)]
    count: Annotated[int, Field(ge=1)]


TOOL_CALLS = TypeAdapter(list[RuntimeToolCall])
EVIDENCE = TypeAdapter(list[Evidence])
LOG_EVENTS = TypeAdapter(list[dict[str, object]])


class RuntimeTraceScope(BaseModel):
    """OpenTelemetry instrumentation scope stored on one exported span."""

    model_config = ConfigDict(extra="allow")

    name: Annotated[str, Field(min_length=1)]


class RuntimeTraceSpan(BaseModel):
    """Evaluation-relevant fields from a CloudWatch OpenTelemetry span."""

    # AgentCore Evaluations requires the complete OTEL document. Keep fields that
    # local smoke checks do not inspect so the trace can be scored without a
    # second CloudWatch read or a lossy reconstruction.
    model_config = ConfigDict(extra="allow")

    scope: RuntimeTraceScope
    trace_id: Annotated[str, Field(alias="traceId", min_length=1)]
    span_id: Annotated[str, Field(alias="spanId", min_length=1)]
    duration_nano: Annotated[int | None, Field(alias="durationNano", ge=0)] = None
    resource: dict[str, object]
    attributes: dict[str, object]


class RuntimeSmokeError(RuntimeError):
    """Raised when the deployed Runtime violates its invocation contract."""


@dataclass(frozen=True, slots=True)
class RuntimeSmokeResult:
    """Validated result of one signed Runtime invocation."""

    candidates: ProjectCandidateSet
    tool_calls: tuple[RuntimeToolCall, ...]
    session_id: str
    content_type: str
    retrieved_evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return the human-readable smoke result."""
        return {
            "iam_authenticated": True,
            "content_type": self.content_type,
            "session_id": self.session_id,
            "retrieved_evidence_ids": list(self.retrieved_evidence_ids),
            "candidates": self.candidates.model_dump(mode="json")["candidates"],
            "tool_calls": [tool_call.model_dump(mode="json") for tool_call in self.tool_calls],
        }


@dataclass(frozen=True, slots=True)
class RuntimeTraceResult:
    """Sanitized summary of evaluation-compatible spans for one Runtime session."""

    spans: tuple[RuntimeTraceSpan, ...]

    def prompt_cache_usage(self) -> tuple[int, int]:
        """Return cache-read and cache-write tokens from the Strands agent span."""
        agent_spans = [
            span
            for span in self.spans
            if span.scope.name == "strands.telemetry.tracer"
            and span.attributes.get("gen_ai.operation.name") == "invoke_agent"
        ]
        if len(agent_spans) != 1:
            raise RuntimeSmokeError("Runtime trace must contain one Strands agent span")

        counters: list[int] = []
        for name in (
            "gen_ai.usage.cache_read_input_tokens",
            "gen_ai.usage.cache_write_input_tokens",
        ):
            value = agent_spans[0].attributes.get(name, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeSmokeError("Runtime trace contains invalid prompt-cache metrics")
            counters.append(value)
        return counters[0], counters[1]

    def as_dict(self) -> dict[str, object]:
        """Return trace metadata without prompts, responses, IDs, or resource ARNs."""
        cache_read_input_tokens, cache_write_input_tokens = self.prompt_cache_usage()
        return {
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "evaluation_scope_present": any(
                span.scope.name == "strands.telemetry.tracer" for span in self.spans
            ),
            "operation_names": sorted(
                {
                    operation
                    for span in self.spans
                    if isinstance(operation := span.attributes.get("gen_ai.operation.name"), str)
                }
            ),
            "scope_names": sorted({span.scope.name for span in self.spans}),
            "service_names": sorted(
                {
                    service_name
                    for span in self.spans
                    if isinstance(service_name := _resource_attribute(span, "service.name"), str)
                }
            ),
            "session_correlated": True,
            "span_count": len(self.spans),
            "trace_count": len({span.trace_id for span in self.spans}),
        }


def create_runtime_client(profile: str | None, region: str) -> RuntimeClient:
    """Create a bounded AgentCore data-plane client with the active AWS identity."""
    session = Session(profile_name=profile, region_name=region)
    return cast(
        "RuntimeClient",
        session.client(  # pyright: ignore[reportUnknownMemberType]
            "bedrock-agentcore",
            config=Config(
                connect_timeout=10,
                read_timeout=300,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        ),
    )


def create_logs_client(profile: str | None, region: str) -> LogsClient:
    """Create the CloudWatch Logs client used for read-only trace verification."""
    session = Session(profile_name=profile, region_name=region)
    return cast(
        "LogsClient",
        session.client(  # pyright: ignore[reportUnknownMemberType]
            "logs",
            config=Config(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        ),
    )


def invoke_runtime_endpoint(
    client: RuntimeClient,
    runtime_arn: str,
    qualifier: str,
    prompt: str,
    session_id: str,
) -> RuntimeSmokeResult:
    """Invoke one named Runtime endpoint and validate its buffered response."""
    if not prompt.strip():
        raise RuntimeSmokeError("prompt must not be empty")
    if len(session_id) < MINIMUM_SESSION_ID_LENGTH:
        raise RuntimeSmokeError("Runtime session ID must contain at least 33 characters")

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            qualifier=qualifier,
            payload=json.dumps({"prompt": prompt.strip()}).encode(),
            contentType=JSON_CONTENT_TYPE,
            accept=JSON_CONTENT_TYPE,
        )
    except (BotoCoreError, ClientError) as error:
        raise RuntimeSmokeError("signed AgentCore Runtime invocation failed") from error

    status_code = response.get("statusCode")
    if status_code != 200:
        raise RuntimeSmokeError(f"AgentCore Runtime returned HTTP {status_code}")
    response_body = response.get("response")
    if response_body is None or not hasattr(response_body, "read"):
        raise RuntimeSmokeError("AgentCore Runtime response body is missing")
    raw_content_type = response.get("contentType", "")
    content_type = raw_content_type if isinstance(raw_content_type, str) else ""

    try:
        payload = JSON_OBJECT.validate_json(cast("ResponseBody", response_body).read())
        candidates = ProjectCandidateSet.model_validate({"candidates": payload.get("candidates")})
        evidence = EVIDENCE.validate_python(payload.get("evidence"))
        tool_calls = tuple(TOOL_CALLS.validate_python(payload.get("tool_calls")))
    except ValidationError as error:
        raise RuntimeSmokeError("AgentCore Runtime returned an invalid agent response") from error
    if not tool_calls:
        raise RuntimeSmokeError("AgentCore Runtime returned no Gateway tool calls")
    retrieved_evidence_ids = tuple(item.evidence_id for item in evidence)
    cited_evidence_ids = {
        citation.evidence_id
        for candidate in candidates.candidates
        for citation in candidate.evidence_citations
    }
    if not cited_evidence_ids <= set(retrieved_evidence_ids):
        raise RuntimeSmokeError("AgentCore Runtime cited evidence outside its retrieval context")

    return RuntimeSmokeResult(
        candidates,
        tool_calls,
        session_id,
        content_type,
        retrieved_evidence_ids,
    )


def _resource_attribute(span: RuntimeTraceSpan, name: str) -> object:
    """Read one attribute from an OTEL resource without trusting its full shape."""
    attributes = span.resource.get("attributes")
    if not isinstance(attributes, dict):
        return None
    return cast("dict[str, object]", attributes).get(name)


def parse_runtime_traces(
    messages: list[str],
    runtime_arn: str,
    session_id: str,
) -> RuntimeTraceResult | None:
    """Parse exported spans and return a result once the Strands agent span arrives."""
    matching: dict[str, RuntimeTraceSpan] = {}
    for message in messages:
        try:
            span = RuntimeTraceSpan.model_validate_json(message)
        except ValidationError:
            continue
        resource_id = _resource_attribute(span, "cloud.resource_id")
        if not isinstance(resource_id, str) or runtime_arn not in resource_id:
            continue
        if span.attributes.get("session.id") != session_id:
            continue
        matching[span.span_id] = span

    spans = tuple(matching.values())
    if not any(
        span.scope.name == "strands.telemetry.tracer"
        and span.attributes.get("gen_ai.operation.name") == "invoke_agent"
        for span in spans
    ):
        return None
    return RuntimeTraceResult(spans=spans)


def runtime_trace_log_group(runtime_arn: str, qualifier: str) -> str:
    """Return the AgentCore endpoint log group that contains the spans stream."""
    runtime_id = runtime_arn.rpartition("/")[2]
    if not runtime_id or not qualifier:
        raise RuntimeSmokeError("Runtime ARN and endpoint qualifier are required for trace lookup")
    return f"/aws/bedrock-agentcore/runtimes/{runtime_id}-{qualifier}"


def wait_for_runtime_traces(
    client: LogsClient,
    log_group_name: str,
    runtime_arn: str,
    session_id: str,
    start_time_ms: int,
    timeout_seconds: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> RuntimeTraceResult:
    """Wait for ADOT to export the invocation's evaluation-compatible Strands span."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            response = client.filter_log_events(
                logGroupName=log_group_name,
                logStreamNames=["spans"],
                startTime=start_time_ms,
                filterPattern=f'"{session_id}"',
            )
        except (BotoCoreError, ClientError) as error:
            raise RuntimeSmokeError("CloudWatch Runtime trace lookup failed") from error
        try:
            events = LOG_EVENTS.validate_python(response.get("events", []))
        except ValidationError:
            events = []
        messages: list[str] = []
        for event in events:
            message = event.get("message")
            if isinstance(message, str):
                messages.append(message)
        result = parse_runtime_traces(messages, runtime_arn, session_id)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise RuntimeSmokeError(
                "No evaluation-compatible Strands span appeared in CloudWatch before the timeout"
            )
        sleep(5)


def main() -> None:
    """Invoke one Runtime session, optionally verifying its trace."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--qualifier", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--verify-traces", action="store_true")
    parser.add_argument("--trace-timeout-seconds", type=int, default=180)
    arguments = parser.parse_args()
    started = int(time.time() * 1000)
    result = invoke_runtime_endpoint(
        create_runtime_client(arguments.profile, arguments.region),
        arguments.runtime_arn,
        arguments.qualifier,
        arguments.prompt,
        str(uuid4()),
    )
    print(f"Runtime returned {len(result.candidates.candidates)} validated candidates.")
    if arguments.verify_traces:
        print("Waiting for the session-correlated Strands trace...", file=sys.stderr)
        traces = wait_for_runtime_traces(
            create_logs_client(arguments.profile, arguments.region),
            runtime_trace_log_group(arguments.runtime_arn, arguments.qualifier),
            arguments.runtime_arn,
            result.session_id,
            started,
            arguments.trace_timeout_seconds,
        )
        print(f"Found {len(traces.spans)} session-correlated spans.")


if __name__ == "__main__":
    main()
