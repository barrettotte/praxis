# ADR 0007: API Gateway HTTP API application boundary

## Status

Superseded in part by ADR 0010 for authorization and Runtime invocation.

## Context

Praxis needs a low-cost public application boundary in front of its private API
Lambda. The boundary must support Cognito JWT authorization and buffered Lambda
responses without exposing AgentCore Runtime directly. The API has four known
routes and does not require REST API features such as API keys, usage plans, or
mapping templates.

## Decision

Use an API Gateway HTTP API with a Lambda proxy integration using payload format
2.0. Deploy the four application routes on an automatically deployed `$default`
stage. Do not create a catch-all route, so unknown paths stop at API Gateway.

Scope Lambda invocation permission to this API's execution ARN. Keep the Lambda
without a function URL. Authorization and downstream permissions are defined by
the Runtime integration decision.

## Consequences

HTTP API provides the required JWT-authorizer and Lambda-proxy capabilities at a
lower price and with less configuration than a REST API. Explicit routes reduce
the exposed surface and allow unknown paths to fail without Lambda invocation.
Features unique to REST APIs would require revisiting this decision if they
become necessary.
