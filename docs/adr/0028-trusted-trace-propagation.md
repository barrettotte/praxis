# Trusted trace propagation

Status: accepted

## Decision

Create application spans without extracting browser trace headers. Carry active
server-generated W3C `traceparent` in an optional SQS String message attribute,
separate from the strict recommendation job body. The single-record worker
continues that remote parent; missing or invalid metadata starts an independent
trace, never inheriting an unrelated delivery context. Accept the version-zero
format emitted by the producer and preserve its sampling flag.

Forward active trace identity through the Runtime SDK's `traceParent` parameter.
Do not propagate vendor state or arbitrary baggage. Existing server correlation
IDs remain separate. The private queue's IAM producer boundary is trusted;
trace metadata never determines actor identity or authorization.

## Consequences

Jobs without trace metadata remain valid. Retries share the producer parent but
create distinct worker spans. Batch processing would require revisiting this
single-parent design. No prompts, evidence, actor IDs, or exception text are
added to application spans. Dependency telemetry is not scrubbed by this policy.
Instrumentation requires an active provider; export configuration and deployed
end-to-end verification are separate requirements.

## Lambda export boundary

Use a package-owned OpenTelemetry provider and a collector-only ADOT Lambda
extension. Keep the Python SDK/exporter locked with the application instead of
combining it with a layer's Python SDK. Do not install automatic library or
handler instrumentation. Enable the provider only with `PRAXIS_LAMBDA_TRACING=true`
inside Lambda; otherwise retain the existing active-provider behavior.

Use a local HTTP/protobuf handoff on `127.0.0.1:4318`, a 0.5-second exporter
timeout, and synchronous span processing so Python does not freeze with pending
spans. Disable proxy/netrc inheritance and override exporter headers. The
collector handles AWS authentication and remote export. Use X-Ray-compatible
IDs and parent-based sampling; roots are sampled for this low-volume demo.
Resource metadata is limited to the configured function name and fixed AWS
platform fields. Do not replace a global provider or enable metrics/Application
Signals. The extension adds memory and latency overhead; deployed measurements
must precede considering tracing verified.

The [AWS collector-only layer documentation](https://aws-otel.github.io/docs/getting-started/lambda/lambda-go/)
describes the extension separately from language SDKs. The
[Python bundled layer](https://aws-otel.github.io/docs/getting-started/lambda/lambda-python/)
is an alternative but requires reviewing its SDK compatibility and automatic
instrumentation behavior.
