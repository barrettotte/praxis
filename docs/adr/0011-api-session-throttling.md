# ADR 0011: API session throttling

## Status

Accepted

## Context

Creating a session invokes the model-backed Runtime and is materially more
expensive than request validation or an unimplemented route. The MVP is
single-user, so concurrent session creation is more likely to be an accidental
double-submit or retry storm than useful throughput.

## Decision

Configure API Gateway route throttling for `POST /v1/sessions` with a burst
limit of one and a steady rate of 0.1 requests per second. Leave other routes
without this override until their handlers establish their own cost and
concurrency characteristics.

Verify the deployed setting by reading the stage's route settings and matching
both values exactly. API Gateway applies throttling on a best-effort basis, so
behavioral load testing belongs with failure testing rather than deterministic
deployment smoke checks. API Gateway documents the rate and burst behavior in its
[HTTP API throttling guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html).

## Consequences

- Only one session creation can enter the API at the start of a burst.
- Rejected callers must back off before retrying.
- The setting limits accidental spend but is not a budget or authorization
  control.
- Additional Runtime-backed routes require explicit limits when connected.
- A demonstrated multi-user throughput requirement would justify revisiting
  these values.
