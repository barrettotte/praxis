"""Tests for private asynchronous recommendation jobs."""

import json

import pytest
from botocore.exceptions import ClientError

from praxis.api.jobs import (
    ApiJobError,
    RecommendationJob,
    enqueue_job,
    load_job_queue_url,
    parse_job_event,
)

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
ACTOR_ID = "7b9db85b-9448-4a41-9bb7-235a461429ae"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/praxis-dev-recommendations"


class FakeQueueClient:
    """Capture one SQS send request or raise a configured error."""

    def __init__(self, error: ClientError | None = None) -> None:
        self.error = error
        self.request: dict[str, object] | None = None

    def send_message(self, **kwargs: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        self.request = kwargs
        return {"MessageId": "message-id"}


def job() -> RecommendationJob:
    return RecommendationJob(
        session_id=SESSION_ID,
        goal="Learn compiler backends",
        correlation_id=CORRELATION_ID,
        actor_id=ACTOR_ID,
    )


def test_queues_minimal_private_job() -> None:
    client = FakeQueueClient()

    enqueue_job(client, QUEUE_URL, job())

    assert client.request == {
        "QueueUrl": QUEUE_URL,
        "MessageBody": job().model_dump_json(),
    }


def test_parses_one_sqs_job() -> None:
    assert (
        parse_job_event(
            {
                "Records": [
                    {
                        "body": job().model_dump_json(),
                        "eventSource": "aws:sqs",
                        "receiptHandle": "ignored",
                    }
                ]
            }
        )
        == job()
    )


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"Records": []},
        {"Records": [{"body": "not-json", "eventSource": "aws:sqs"}]},
        {"Records": [{"body": json.dumps({"goal": "missing identity"}), "eventSource": "aws:sqs"}]},
        {"Records": [{"body": job().model_dump_json(), "eventSource": "aws:sns"}]},
    ],
)
def test_rejects_invalid_job_events(event: object) -> None:
    with pytest.raises(ApiJobError, match="invalid recommendation job"):
        parse_job_event(event)


def test_hides_queue_failure_details() -> None:
    client = FakeQueueClient(
        ClientError(
            {"Error": {"Code": "InternalError", "Message": "sensitive queue detail"}},
            "SendMessage",
        )
    )

    with pytest.raises(ApiJobError, match="could not be queued") as captured:
        enqueue_job(client, QUEUE_URL, job())

    assert "sensitive queue detail" not in str(captured.value)


def test_requires_https_queue_configuration() -> None:
    assert load_job_queue_url({"PRAXIS_RECOMMENDATION_QUEUE_URL": QUEUE_URL}) == QUEUE_URL
    with pytest.raises(ApiJobError, match="invalid recommendation queue configuration"):
        load_job_queue_url({})
