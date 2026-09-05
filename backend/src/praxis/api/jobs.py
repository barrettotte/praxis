"""Queue bounded recommendation jobs without exposing Runtime to public clients."""

import os
from collections.abc import Mapping
from functools import cache
from typing import Annotated, Literal, Protocol, cast

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from praxis.api.requests import MAX_API_TEXT_CHARACTERS, ActorId, SessionId


class ApiJobError(RuntimeError):
    """Raised when a recommendation job cannot be validated or queued."""


class QueueClient(Protocol):
    """SQS operation used by the authenticated API Lambda."""

    def send_message(self, **kwargs: object) -> dict[str, object]: ...


class RecommendationJob(BaseModel):
    """Private work item consumed by the recommendation worker Lambda."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    session_id: SessionId
    goal: Annotated[str, Field(min_length=1, max_length=MAX_API_TEXT_CHARACTERS)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    actor_id: ActorId


class _SqsRecord(BaseModel):
    """SQS event fields required by the worker."""

    model_config = ConfigDict(extra="ignore", strict=True)

    body: str
    event_source: Literal["aws:sqs"] = Field(alias="eventSource")
    message_attributes: object = Field(default=None, alias="messageAttributes")


class _SqsEvent(BaseModel):
    """Require one job per worker invocation."""

    model_config = ConfigDict(extra="ignore", strict=True)

    records: Annotated[list[_SqsRecord], Field(alias="Records", min_length=1, max_length=1)]


def load_job_queue_url(environment: Mapping[str, str] | None = None) -> str:
    """Load the deployment-owned recommendation queue URL."""
    source = os.environ if environment is None else environment
    queue_url = source.get("PRAXIS_RECOMMENDATION_QUEUE_URL", "").strip()
    if not queue_url.startswith("https://"):
        raise ApiJobError("invalid recommendation queue configuration")
    return queue_url


@cache
def create_queue_client() -> QueueClient:
    """Create one bounded SQS client for authenticated API requests."""
    try:
        return cast(
            "QueueClient",
            Session().client(  # pyright: ignore[reportUnknownMemberType]
                "sqs",
                config=Config(
                    connect_timeout=2,
                    read_timeout=2,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            ),
        )
    except BotoCoreError as error:
        raise ApiJobError("recommendation queue client initialization failed") from error


def enqueue_job(client: QueueClient, queue_url: str, job: RecommendationJob) -> None:
    """Submit one private recommendation job to the encrypted queue."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    # Transport only server-generated trace identity, never baggage or vendor state.
    metadata = (
        {
            "MessageAttributes": {
                "traceparent": {"DataType": "String", "StringValue": carrier["traceparent"]}
            }
        }
        if "traceparent" in carrier
        else {}
    )
    try:
        client.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json(), **metadata)
    except (BotoCoreError, ClientError) as error:
        raise ApiJobError("recommendation job could not be queued") from error


def job_trace_context(event: object) -> Context:
    """Extract optional queue trace identity without inheriting another delivery's context."""
    try:
        attributes = _SqsEvent.model_validate(event).records[0].message_attributes
    except ValidationError:
        return Context()
    if not isinstance(attributes, dict):
        return Context()
    attribute = cast("dict[str, object]", attributes).get("traceparent")
    if not isinstance(attribute, dict):
        return Context()
    fields = cast("dict[str, object]", attribute)
    value = fields.get("stringValue")
    if (
        fields.get("dataType") != "String"
        or not isinstance(value, str)
        or len(value) != 55
        or not value.startswith("00-")
    ):
        return Context()
    # Accept the W3C version-zero format emitted by this producer; ignore all other metadata.
    return TraceContextTextMapPropagator().extract({"traceparent": value}, context=Context())


def parse_job_event(event: object) -> RecommendationJob:
    """Validate one SQS event without retaining malformed content."""
    try:
        envelope = _SqsEvent.model_validate(event)
        return RecommendationJob.model_validate_json(envelope.records[0].body)
    except (IndexError, ValidationError) as error:
        raise ApiJobError("invalid recommendation job") from error
