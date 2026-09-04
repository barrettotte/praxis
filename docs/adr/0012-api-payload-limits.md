# ADR 0012: Application API payload limits

## Status

Accepted

## Context

The AWS transport limits are much larger than a single-user planning request:
API Gateway HTTP APIs accept payloads up to 10 MB, and synchronous Lambda
invocations accept request payloads up to 6 MB. Passing an unnecessarily large
body into JSON validation or a model-backed handler wastes memory and increases
the impact of accidental or hostile requests.

## Decision

Limit every decoded application JSON body to 16 KiB and limit the public `goal`
field to 4,000 characters. Measure raw request bodies as UTF-8 bytes and
base64-encoded bodies after decoding. Reject bodies over the byte limit before
JSON parsing and before route handlers with a fixed
`payload_too_large` response and HTTP status 413. Continue to return the fixed
400 response for smaller requests that violate the JSON contract.

Verify deployment through direct Lambda invocation with synthetic trusted JWT
context. The smoke check sends both a body above 16 KiB and a goal of 4,001
characters, requires the fixed 413 and 400 envelopes, and records that the
Runtime-backed handler was not reached.

The transport ceilings are documented in the AWS
[HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)
and [Lambda Invoke API](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html)
references.

## Consequences

- Oversized requests fail without model cost or submitted-content reflection.
- Clients must size JSON as encoded UTF-8 rather than relying only on character
  count.
- The application limit remains stable even if AWS transport quotas change.
- Raising either limit requires contract, test, documentation, and deployment
  evidence updates.
