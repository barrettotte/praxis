# ADR 0016: Cognito browser application client

## Status

Accepted

## Context

The React application needs to authenticate directly with the Cognito user
pool. A browser cannot protect a client secret, and the application does not
need federated identity providers or a Cognito-managed login page.

## Decision

Use a public Cognito application client without a client secret. Permit only
Secure Remote Password (SRP) authentication and refresh-token authentication
through the Cognito identity provider. Do not enable OAuth redirect flows.

Issue access and ID tokens for one hour and refresh tokens for seven days.
Enable token revocation and suppress user-existence errors. Limit readable user
attributes to the verified email identity required by the application. Store
tokens in browser session storage so closing the tab ends the local session.

OpenTofu exports the non-secret client identifier for frontend configuration.
It does not manage users, passwords, tokens, or browser session state.

## Consequences

- The frontend can authenticate without embedding a credential or operating a
  client-secret exchange service.
- Browser sessions survive a reload but do not persist after the tab closes.
- Login and logout use Cognito's user-pool APIs rather than redirecting through
  a hosted login page.
- The API Gateway JWT authorizer can restrict accepted tokens to this client.
- Adding federation or managed-login redirects requires a separate decision and
  explicit callback and logout URL allowlists.
