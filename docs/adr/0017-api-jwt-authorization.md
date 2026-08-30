# ADR 0017: API JWT authorization

## Status

Accepted

## Context

The public application API can trigger metered AgentCore Runtime work and must
authenticate browser requests before Lambda invocation. The browser client is a
public Cognito client and cannot use AWS credentials or protect a shared secret.

## Decision

Protect every declared API Gateway route with its native JWT authorizer. Trust
only the issuer for the application Cognito user pool and only the audience of
the public browser client. Read bearer tokens exclusively from the
`Authorization` header. The frontend sends Cognito access tokens when calling
the API.

Do not use AWS IAM authorization or a custom Lambda authorizer at the
application boundary. API Gateway continues to own CORS preflight responses,
which do not invoke the API Lambda. Unknown routes remain undeclared.

## Consequences

- Missing, expired, malformed, or incorrectly issued tokens are rejected before
  Lambda and Runtime invocation.
- Every application route shares one explicit issuer and audience contract.
- End-to-end API checks require a short-lived Cognito access token; AWS CLI
  credentials no longer authorize application requests.
- JWT validation does not replace request validation, throttling, or the private
  IAM boundaries between Lambda, Runtime, Gateway, and tools.
