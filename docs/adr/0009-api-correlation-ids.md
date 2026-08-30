# ADR 0009: API correlation IDs

## Status

Accepted

## Context

Requests need a stable identifier that can eventually connect API access logs,
Lambda logs, and downstream Runtime calls. Public header values cannot be copied
into responses or telemetry without validation.

## Decision

The application API accepts an optional `x-correlation-id` header only when it
is a canonical lowercase UUIDv4. Otherwise, it selects API Gateway's trusted
request ID. Every Lambda response returns the selected value in the
`x-correlation-id` header, including fixed error responses.

An invalid client correlation ID makes the request invalid, while the error
response uses a trusted Gateway, Lambda, or generated UUIDv4 fallback. The ID is
transport metadata and does not appear in JSON response bodies or evidence
captures. Downstream application adapters must reuse the selected ID when they
are connected.

## Consequences

- Clients can connect their request and response without controlling arbitrary
  response-header content.
- Requests without a client ID remain traceable using AWS request metadata.
- Logging and Runtime propagation can adopt the same value without changing the
  public response schema.
- Unknown routes handled solely by API Gateway do not pass through this Lambda
  correlation boundary.
