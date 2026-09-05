"""Tests for private asynchronous recommendation jobs."""

import json
from typing import cast
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from opentelemetry import baggage, trace
from opentelemetry.context import attach, detach
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from praxis.api.jobs import (
    ApiJobError,
    RecommendationJob,
    enqueue_job,
    job_trace_context,
    load_job_queue_url,
    parse_job_event,
)
from praxis.functions import recommendation_worker

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
    assert not trace.get_current_span(job_trace_context(event)).get_span_context().is_valid
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


@pytest.mark.parametrize("sampled", [True, False])
def test_queue_trace_identity_round_trip(sampled: bool) -> None:
    client = FakeQueueClient()
    parent = trace.SpanContext(
        trace_id=123,
        span_id=456,
        is_remote=False,
        trace_flags=trace.TraceFlags(1 if sampled else 0),
        trace_state=trace.TraceState([("vendor", "private-marker")]),
    )
    token = attach(baggage.set_baggage("private", "private-marker"))
    try:
        with trace.use_span(trace.NonRecordingSpan(parent)):
            enqueue_job(client, QUEUE_URL, job())
    finally:
        detach(token)
    assert client.request is not None
    attributes = cast("dict[str, dict[str, str]]", client.request["MessageAttributes"])
    assert set(attributes) == {"traceparent"}
    assert "private-marker" not in json.dumps(client.request)
    assert client.request["MessageBody"] == job().model_dump_json()
    event = queue_event(
        {
            "traceparent": {
                "dataType": attributes["traceparent"]["DataType"],
                "stringValue": attributes["traceparent"]["StringValue"],
            },
            "baggage": {"dataType": "String", "stringValue": "private=private-marker"},
            "tracestate": {"dataType": "String", "stringValue": "vendor=private-marker"},
        }
    )
    context = job_trace_context(event)
    restored = trace.get_current_span(context).get_span_context()
    assert restored.trace_id == parent.trace_id
    assert restored.span_id == parent.span_id
    assert restored.trace_flags.sampled == sampled
    assert restored.is_remote
    assert not restored.trace_state
    assert not baggage.get_all(context)
    assert parse_job_event(event) == job()


def queue_event(attributes: object) -> dict[str, object]:
    return {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": job().model_dump_json(),
                "messageAttributes": attributes,
            }
        ]
    }


@pytest.mark.parametrize(
    "attributes",
    [
        None,
        {},
        "invalid",
        {"traceparent": None},
        {"traceparent": {"dataType": "String", "stringValue": 123}},
        {"traceparent": {"dataType": "Binary", "stringValue": "0" * 55}},
        {"traceparent": {"dataType": "String", "stringValue": "0" * 55}},
        {"traceparent": {"dataType": "String", "stringValue": "x" * 1000}},
    ],
)
def test_optional_trace_metadata_never_breaks_job_or_inherits_context(attributes: object) -> None:
    parent = trace.NonRecordingSpan(trace.SpanContext(123, 456, False))
    event = queue_event(attributes)
    with trace.use_span(parent):
        context = job_trace_context(event)
    assert not trace.get_current_span(context).get_span_context().is_valid
    assert parse_job_event(event) == job()


def test_worker_span_continues_queue_parent() -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.queue")
    event = queue_event(
        {
            "traceparent": {
                "dataType": "String",
                "stringValue": "00-0000000000000000000000000000007b-00000000000001c8-01",
            }
        }
    )
    try:
        with (
            patch.object(recommendation_worker, "tracer", tracer),
            patch.object(recommendation_worker, "process_job", return_value="ready") as process,
            tracer.start_as_current_span("unrelated.delivery"),
        ):
            assert recommendation_worker.lambda_handler(event, None) == {"processed": 1}
        process.assert_called_once_with(job())
        span = exporter.get_finished_spans()[0]
        assert span.name == "praxis.worker.delivery"
        assert span.parent is not None
        assert span.parent.trace_id == 123
        assert span.parent.span_id == 456
        assert span.parent.is_remote
    finally:
        provider.shutdown()
