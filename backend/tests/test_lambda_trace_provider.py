"""Verify the opt-in Lambda provider without exporting over the network."""

from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from praxis.functions import tracing


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"PRAXIS_LAMBDA_TRACING": "true"},
        {
            "AWS_LAMBDA_FUNCTION_NAME": "praxis-test",
            "PRAXIS_LAMBDA_TRACING": "false",
        },
    ],
)
def test_disabled_provider_does_not_construct_exporter(environment: dict[str, str]) -> None:
    with (
        patch.dict("os.environ", environment, clear=True),
        patch.object(tracing, "lambda_trace_provider") as factory,
    ):
        tracing.lambda_tracer("test")
    factory.assert_not_called()


def test_enabled_provider_reuses_exporter_and_preserves_sampling() -> None:
    exporter = InMemorySpanExporter()
    tracing.lambda_trace_provider.cache_clear()
    global_provider = trace.get_tracer_provider()
    try:
        with (
            patch.dict(
                "os.environ",
                {
                    "AWS_LAMBDA_FUNCTION_NAME": "praxis-test",
                    "PRAXIS_LAMBDA_TRACING": "true",
                    "OTEL_EXPORTER_OTLP_HEADERS": "authorization=private-marker",
                },
                clear=True,
            ),
            patch.object(tracing, "OTLPSpanExporter", return_value=exporter) as factory,
        ):
            tracer = tracing.lambda_tracer("test")
            assert tracing.lambda_tracer("test") is not None
            with tracer.start_as_current_span("test.root"):
                pass
            parent = trace.NonRecordingSpan(trace.SpanContext(123, 456, True))
            with tracer.start_as_current_span(
                "unsampled", context=trace.set_span_in_context(parent)
            ):
                pass
            factory.assert_called_once()
            arguments = factory.call_args.kwargs
            assert arguments["endpoint"] == "http://127.0.0.1:4318/v1/traces"
            assert arguments["timeout"] == 2
            assert arguments["headers"] == {"Content-Type": "application/x-protobuf"}
            assert arguments["session"].trust_env is False
            spans = exporter.get_finished_spans()
            assert len(spans) == 1
            assert spans[0].resource.attributes == {
                "service.name": "praxis-test",
                "cloud.provider": "aws",
                "cloud.platform": "aws_lambda",
            }
            assert trace.get_tracer_provider() is global_provider
    finally:
        if tracing.lambda_trace_provider.cache_info().currsize:
            tracing.lambda_trace_provider().shutdown()
        tracing.lambda_trace_provider.cache_clear()
