"""Validate platform trace extraction without payloads or network access."""

import pytest
from opentelemetry import trace

from praxis.functions.tracing import lambda_invocation_trace_context

HEADER = "Root=1-12345678-901234567890123456789012;Parent=1234567890123456;Sampled=1"


@pytest.mark.parametrize("sampled", [False, True])
def test_platform_parent_preserves_identity_and_sampling(
    monkeypatch: pytest.MonkeyPatch, sampled: bool
) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "test-catalog")
    monkeypatch.setenv("_X_AMZN_TRACE_ID", HEADER[:-1] + str(int(sampled)) + ";Lineage=ignored")
    parent = trace.get_current_span(lambda_invocation_trace_context()).get_span_context()
    assert parent.is_remote
    assert parent.trace_id == 0x12345678901234567890123456789012
    assert parent.span_id == 0x1234567890123456
    assert parent.trace_flags.sampled == sampled
    assert not parent.trace_state


@pytest.mark.parametrize(
    "header",
    [
        "",
        "invalid",
        "x" * 1025,
        HEADER.replace("Sampled=1", "Sampled=?"),
        HEADER.replace("Sampled=1", ""),
        HEADER + ";Parent=1234567890123456",
        HEADER.replace("Parent=1234567890123456", "Parent=0000000000000000"),
        HEADER.replace(
            "1-12345678-901234567890123456789012", "1-00000000-000000000000000000000000"
        ),
        HEADER.replace("Parent=1234567890123456", "Parent=not-a-span-id"),
    ],
)
def test_invalid_platform_parent_never_inherits_ambient_context(
    monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "test-catalog")
    monkeypatch.setenv("_X_AMZN_TRACE_ID", header)
    ambient = trace.SpanContext(trace_id=1, span_id=2, is_remote=False)
    with trace.use_span(trace.NonRecordingSpan(ambient)):
        parent = trace.get_current_span(lambda_invocation_trace_context()).get_span_context()
    assert not parent.is_valid


def test_platform_header_is_ignored_outside_lambda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("_X_AMZN_TRACE_ID", HEADER)
    assert not trace.get_current_span(lambda_invocation_trace_context()).get_span_context().is_valid


def test_parent_is_read_for_each_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "test-catalog")
    monkeypatch.setenv("_X_AMZN_TRACE_ID", HEADER)
    first = trace.get_current_span(lambda_invocation_trace_context()).get_span_context()
    monkeypatch.setenv(
        "_X_AMZN_TRACE_ID", HEADER.replace("Parent=1234567890123456", "Parent=abcdefabcdefabcd")
    )
    second = trace.get_current_span(lambda_invocation_trace_context()).get_span_context()
    assert first.span_id != second.span_id
    monkeypatch.delenv("_X_AMZN_TRACE_ID")
    assert not trace.get_current_span(lambda_invocation_trace_context()).get_span_context().is_valid
