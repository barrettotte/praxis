"""Queue bounded recommendation jobs without exposing Runtime to public clients."""

import os
from collections.abc import Mapping
from functools import cache
from typing import Annotated, Literal, Protocol, cast

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from praxis.api.requests import MAX_API_TEXT_CHARACTERS, SessionId


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


class _SqsRecord(BaseModel):
    """SQS event fields required by the worker."""

    model_config = ConfigDict(extra="ignore", strict=True)

    body: str
    event_source: Literal["aws:sqs"] = Field(alias="eventSource")


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
    try:
        client.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())
    except (BotoCoreError, ClientError) as error:
        raise ApiJobError("recommendation job could not be queued") from error


def parse_job_event(event: object) -> RecommendationJob:
    """Validate one SQS event without retaining malformed content."""
    try:
        envelope = _SqsEvent.model_validate(event)
        return RecommendationJob.model_validate_json(envelope.records[0].body)
    except (IndexError, ValidationError) as error:
        raise ApiJobError("invalid recommendation job") from error
