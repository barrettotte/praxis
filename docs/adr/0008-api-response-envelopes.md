# ADR 0008: Application API response envelopes

## Status

Accepted

## Context

The frontend needs predictable JSON across application routes, while operational
and dependency failures must not expose validation details, stack traces,
submitted values, or upstream service exceptions. Human-readable messages can
change, so clients need stable values for programmatic handling.

## Decision

Wrap successful route data under a top-level `data` field. Wrap errors under a
top-level `error` field containing a stable snake-case `code` and safe `message`.
Map each error code to one HTTP status and message inside the API boundary rather
than accepting arbitrary exception text.

Return all Lambda proxy responses as non-cacheable JSON with
`isBase64Encoded: false`. Validate response envelopes with strict Pydantic
models before serialization.

## Consequences

Clients can distinguish success from failure by envelope shape and branch on a
stable error code. New application outcomes require an explicit code and HTTP
mapping. Route-specific success data still needs its own strict model; the
common envelope does not replace domain response validation.
