"""Verify content-free Lambda spans without a network exporter."""

from unittest.mock import patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from praxis.functions import api, catalog, recommendation_worker


def test_catalog_span_uses_platform_parent_not_tool_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "test-catalog")
    monkeypatch.setenv(
        "_X_AMZN_TRACE_ID",
        "Root=1-12345678-901234567890123456789012;Parent=1234567890123456;Sampled=1",
    )
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.catalog")
    try:
        with (
            patch.object(catalog, "tracer", tracer),
            patch.object(catalog, "_handle_request", return_value={}),
            tracer.start_as_current_span("unrelated"),
        ):
            catalog.lambda_handler({"traceparent": "private-payload-marker"}, None)
        span = next(s for s in exporter.get_finished_spans() if s.name == "praxis.catalog.request")
        assert span.context is not None
        assert span.context.trace_id == 0x12345678901234567890123456789012
        assert span.parent is not None
        assert span.parent.span_id == 0x1234567890123456
        assert span.parent.is_remote
        assert "private-payload-marker" not in span.to_json()
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    ("component", "result"),
    [
        ("api", 202),
        ("api", 400),
        ("api", 503),
        ("api", None),
        ("worker", "ready"),
        ("worker", "failed"),
        ("worker", None),
    ],
)
def test_handler_span_preserves_behavior_without_content(
    component: str, result: int | str | None
) -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.lambda")
    module = api if component == "api" else recommendation_worker
    target = "_handle_request" if component == "api" else "process_job"
    marker = "private request response identity and exception text"
    failure = RuntimeError(marker)
    response = {"statusCode": result, "body": marker}

    def work(*_args: object) -> object:
        with tracer.start_as_current_span("test.child"):
            pass
        if result is None:
            raise failure
        return response if component == "api" else result

    try:
        with (
            patch.object(module, "tracer", tracer),
            patch.object(module, target, side_effect=work),
            patch.object(recommendation_worker, "parse_job_event", return_value=object()),
            tracer.start_as_current_span("test.parent"),
        ):
            if result is None:
                with pytest.raises(RuntimeError) as captured:
                    module.lambda_handler({"body": marker}, object())
                assert captured.value is failure
            else:
                returned = module.lambda_handler({"body": marker}, object())
                if component == "api":
                    assert returned is response
                else:
                    assert returned == {"processed": 1}
        spans = {span.name: span for span in exporter.get_finished_spans()}
        name = "praxis.api.request" if component == "api" else "praxis.worker.delivery"
        span = spans[name]
        expected: dict[str, str | int] = {}
        if component == "api":
            expected["praxis.outcome"] = "unhandled_error" if result is None else "responded"
            if isinstance(result, int):
                expected["http.response.status_code"] = result
        else:
            expected["praxis.outcome"] = "retry" if result is None else str(result)
        assert span.attributes == expected
        is_error = result is None or result in (503, "failed")
        assert span.status.status_code == (StatusCode.ERROR if is_error else StatusCode.UNSET)
        assert span.status.description is None
        assert span.events == ()
        assert span.parent == (spans["test.parent"].context if component == "api" else None)
        assert spans["test.child"].parent == span.context
        assert span.start_time is not None
        assert span.end_time is not None
        assert span.end_time >= span.start_time
        assert marker not in span.to_json()
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    "outcome", ["success", "INVALID_ARGUMENTS", "DEPENDENCY_FAILURE", "unexpected"]
)
def test_catalog_span_preserves_result_and_safe_outcome(outcome: str) -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.catalog")
    marker = "private query evidence and diagnostic text"
    response: dict[str, object] = {"results": [marker]}
    error = (
        catalog.CatalogToolError("INVALID_ARGUMENTS", marker, retryable=False)
        if outcome == "INVALID_ARGUMENTS"
        else catalog.CatalogToolError("DEPENDENCY_FAILURE", marker, retryable=True)
        if outcome == "DEPENDENCY_FAILURE"
        else RuntimeError(marker)
    )

    def work(*_args: object) -> dict[str, object]:
        with tracer.start_as_current_span("test.child"):
            pass
        if outcome != "success":
            raise error
        return response

    try:
        with (
            patch.object(catalog, "tracer", tracer),
            patch.object(catalog, "_handle_request", side_effect=work),
            tracer.start_as_current_span("test.parent"),
        ):
            if outcome == "success":
                assert catalog.lambda_handler({"query": marker}, None) is response
            else:
                with pytest.raises(type(error)) as captured:
                    catalog.lambda_handler({"query": marker}, None)
                assert captured.value is error
        spans = {span.name: span for span in exporter.get_finished_spans()}
        span = spans["praxis.catalog.request"]
        assert span.attributes == {
            "praxis.outcome": "INTERNAL_ERROR" if outcome == "unexpected" else outcome
        }
        assert span.status.status_code == (
            StatusCode.UNSET if outcome == "success" else StatusCode.ERROR
        )
        assert span.status.description is None
        assert not span.events
        assert span.parent is None
        assert spans["test.child"].parent == span.context
        assert span.start_time is not None
        assert span.end_time is not None
        assert span.end_time >= span.start_time
        assert marker not in span.to_json()
    finally:
        provider.shutdown()
