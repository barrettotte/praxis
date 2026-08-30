# ADR 0013: Privacy-safe API access logging

## Status

Accepted

## Context

API requests need enough transport telemetry to diagnose authorization,
integration, latency, and response-size failures. Default access-log examples
include caller IP addresses, while error fields and raw paths can expose
sensitive input or session identifiers. The single-user development environment
does not need that data for operational verification.

## Decision

Enable JSON access logging on the API Gateway default stage. Store records in a
dedicated CloudWatch log group with seven-day retention. Include only the API
Gateway request ID, request time, HTTP method, route template, response status,
response latency and length, and Lambda integration request ID, status, and
latency.

Do not log request or response bodies, prompts, raw paths, query strings, IP
addresses, user agents, caller identities, authorization details, or service
error text. Verify both the exact stage format and actual CloudWatch delivery by
correlating an unsigned declared-route request that API Gateway rejects before
Lambda invocation.

API Gateway requires the access-log format to include `$context.requestId` and
documents the available variables in its
[HTTP API logging guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging.html)
and [HTTP API access-log variable reference](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html).

## Consequences

- Authorization failures and integration behavior are observable without
  retaining submitted content or direct caller identifiers.
- Access records expire automatically with the rest of the disposable
  development logs.
- Application correlation IDs remain Lambda response metadata; API Gateway
  access records use the Gateway request ID because HTTP API access-log
  variables do not expose arbitrary response headers.
- Additional fields require a privacy review and an update to the exact-schema
  smoke check.
