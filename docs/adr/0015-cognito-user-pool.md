# ADR 0015: Cognito application user directory

## Status

Accepted

## Context

The browser application needs a user identity boundary before API Gateway can
replace its temporary IAM caller authorization with JWT authorization. Praxis
is a single-user application with no public registration requirement, and its
development environment must remain inexpensive and disposable.

## Decision

Use an Amazon Cognito user pool in the Lite feature tier. Accept a
case-insensitive email address as the sign-in name, automatically verify email,
and allow account recovery only through verified email. Disable public
self-registration so only an administrator can create the application user.

Require a 14-character password containing lowercase, uppercase, numeric, and
symbol characters. Temporary passwords expire after seven days. Keep MFA off
until the frontend supports its enrollment and challenge flows; adding MFA
requires a reviewed update to this decision.

Use Cognito's default email delivery for the single development user. Do not
manage application users or passwords with OpenTofu because credentials and
temporary passwords do not belong in infrastructure state. Keep deletion
protection inactive so the guarded development teardown remains complete.

The pool configuration follows AWS guidance to avoid public self-registration
unless it is an intended product feature and to use case-insensitive usernames:

- [Amazon Cognito user pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html)
- [User pool case sensitivity](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-case-sensitivity.html)

## Consequences

- Applying the infrastructure creates an empty user directory, not an
  application user or credential.
- The future browser client can use email for sign-in while treating the stable
  Cognito `sub` claim as the user identity.
- The app client and API Gateway JWT authorizer require separate reviewed
  resources and verification.
- Destroying the temporary development stack also destroys its user directory.
