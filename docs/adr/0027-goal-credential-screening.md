# Goal credential screening

Status: accepted

## Context

Goals are persisted before asynchronous generation, and evaluation traces can
contain model input and output. Prompt instructions and Bedrock Guardrails
cannot guarantee that pasted credentials stay out of storage or telemetry.

## Decision

Screen decoded, validated goals inside the API Lambda before persistence or
queue submission. Use local pattern checks for recognizable credential formats
and explicit credential assignments, without network services or model calls.
Reject matches with a fixed `400 sensitive_input` response, not matched text or
silent redaction. The browser shows a fixed correction message and a warning
against submitting credentials. Keep API access logs metadata-only.

Reuse the detector at the Runtime JSON payload boundary before schema validation
or Memory access, and in the CLI before catalog loading. Screen assembled local,
Gateway, and brief-generation context before Strands invocation. Replace detected
credential-bearing model-selected tool results with a fixed error using the
existing evidence hook; do not retain those facts in its ledger. Runtime input
rejections return a fixed HTTP 400 without exposing matched content.

## Consequences

This reduces accidental disclosure through new public sessions; it is not a
general secret/PII detector. Synthetic examples can be false positives. Unknown
formats, unlabelled passwords, encoded values, and sensitive prose can pass.
Stored sessions, authoritative catalog and memory data, and generated output are
not scrubbed. Retrieval and SDK exception diagnostics may be recorded before
application screening, and CLI arguments can enter shell history/process listings.
Content tracing still requires restricted access, short retention, and
non-sensitive inputs. Existing data is not scrubbed.

Tests must verify rejection before storage, queueing, or Runtime invocation,
including base64 transport, without echoing matches in responses or application
logs. The API smoke suite checks the deployed response using synthetic data only.
