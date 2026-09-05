"""Opt-in application tracing through a local Lambda collector."""

import os
import re
from functools import cache

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.extension.aws.trace import (  # pyright: ignore[reportMissingTypeStubs]
    AwsXRayIdGenerator,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from requests import Session


def lambda_invocation_trace_context() -> Context:
    """Read only the platform's per-invocation parent, never payload or ambient context."""
    empty = Context()
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return empty
    header = os.environ.get("_X_AMZN_TRACE_ID", "")
    if not header or len(header) > 1024:
        return empty
    fields: dict[str, str] = {}
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if name not in {"Root", "Parent", "Sampled"}:
            continue
        if not separator or name in fields:
            return empty
        fields[name] = value
    root = fields.get("Root", "")
    parent = fields.get("Parent", "")
    sampled = fields.get("Sampled", "")
    if (
        not re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", root)
        or not re.fullmatch(r"[0-9a-f]{16}", parent)
        or sampled not in {"0", "1"}
    ):
        return empty
    # Reuse W3C validation for nonzero IDs; discard X-Ray extension fields.
    trace_id = root[2:].replace("-", "")
    return TraceContextTextMapPropagator().extract(
        {"traceparent": f"00-{trace_id}-{parent}-0{sampled}"}, context=empty
    )


@cache
def lambda_trace_provider() -> TracerProvider:
    """Own one provider per execution environment without replacing global instrumentation."""
    provider = TracerProvider(
        resource=Resource(
            {
                "service.name": os.environ["AWS_LAMBDA_FUNCTION_NAME"],
                "cloud.provider": "aws",
                "cloud.platform": "aws_lambda",
            }
        ),
        id_generator=AwsXRayIdGenerator(),
        sampler=ParentBased(ALWAYS_ON),
    )
    # Complete the local handoff before Lambda freezes Python; the extension exports remotely.
    # Explicit headers prevent unrelated OTLP environment headers from being forwarded.
    session = Session()
    session.trust_env = False
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPSpanExporter(
                endpoint="http://127.0.0.1:4318/v1/traces",
                timeout=2,
                headers={"Content-Type": "application/x-protobuf"},
                session=session,
            )
        )
    )
    return provider


def lambda_tracer(name: str) -> trace.Tracer:
    """Use the collector only when explicitly enabled inside a Lambda environment."""
    if os.environ.get("PRAXIS_LAMBDA_TRACING") == "true" and os.environ.get(
        "AWS_LAMBDA_FUNCTION_NAME"
    ):
        return lambda_trace_provider().get_tracer(name)
    return trace.get_tracer(name)
