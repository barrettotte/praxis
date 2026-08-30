# ADR 0014: Exact-origin API CORS

## Status

Accepted

## Context

The browser application and API use different origins, so browsers require a
CORS preflight before JSON requests carrying authorization and correlation
headers. A wildcard origin would allow any website to initiate browser requests
and would obscure the intended frontend boundary. CORS is enforced by browsers
and is not an authorization control.

## Decision

Configure CORS on the API Gateway HTTP API with one exact frontend origin. Use
`http://localhost:5173` for development and expose it as a validated OpenTofu
input so the reviewed frontend deployment can replace it with an HTTPS origin.

Allow GET, POST, and OPTIONS; allow only `authorization`, `content-type`, and
`x-correlation-id`; expose only `x-correlation-id`; and cache preflight results
for five minutes. Do not allow credentials because authentication uses an
explicit authorization header rather than ambient cookies. Let API Gateway
answer preflight requests without Lambda invocation.

Verify the exact deployed configuration, a successful configured-origin
preflight, and omission of the allow-origin header for an unrelated origin.
AWS documents the managed preflight and response behavior in its
[HTTP API CORS guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html).

## Consequences

- Browser requests are limited to the reviewed frontend origin and public API
  surface.
- Direct HTTP clients remain governed by API authorization rather than CORS.
- Frontend hosting changes require a reviewed plan with the new exact origin.
- Adding a method or public request header requires updating the CORS contract
  and its deployment smoke check.
