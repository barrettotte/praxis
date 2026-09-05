"""Opt-in application tracing through a local Lambda collector."""

import os
from functools import cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.extension.aws.trace import (  # pyright: ignore[reportMissingTypeStubs]
    AwsXRayIdGenerator,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from requests import Session


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
                timeout=0.5,
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
