# ADR 0011: API session throttling

## Status

Accepted

## Context

Creating a session invokes the model-backed Runtime and is materially more
expensive than request validation or an unimplemented route. The MVP is
single-user, so concurrent session creation is more likely to be an accidental
double-submit or retry storm than useful throughput.

## Decision

Configure API Gateway route throttling for `POST /v1/sessions` and
`POST /v1/projects/{candidateId}/select` with a burst limit of one and a steady
rate of 0.1 requests per second. Both routes can start metered model work.

Verify the deployed setting by reading the stage's route settings and matching
both values exactly. API Gateway applies throttling on a best-effort basis, so
the smoke does not require a small request burst to produce a 429. Local tests
inject throttling responses and verify safe errors without automatic browser
resubmission. Live saturation is not part of this verification. API Gateway
documents the rate and burst behavior in its
[HTTP API throttling guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html).

## Consequences

- A burst limit of one is a best-effort target, not a strict concurrency cap.
- Rejected callers must back off before retrying.
- The setting limits accidental spend but is not a budget or authorization
  control.
- Additional Runtime-backed routes require explicit limits when connected.
- A demonstrated multi-user throughput requirement would justify revisiting
  these values.
