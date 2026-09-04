# ADR 0019: Private S3 and CloudFront frontend hosting

## Status

Accepted

## Context

The browser application needs a temporary HTTPS deployment that preserves API
Gateway as the application boundary. The application is a static Vite bundle
and does not require an origin server, custom domain, or server-side rendering.
Direct public S3 hosting would create a second public origin and would not
provide the intended HTTPS delivery boundary.

## Decision

Store the production frontend bundle in a private, encrypted S3 bucket with all
public-access controls enabled. Serve it only through a CloudFront distribution
using origin access control and signed requests. Use the CloudFront-managed
certificate and domain, the lowest-cost geographic price class, the managed
optimized cache policy, and the managed security-headers policy. Map S3 403 and
404 responses to `index.html` so client-side routes load the application shell.

Keep static asset publication separate from infrastructure reconciliation. A
confirmed script builds Vite with the public API and Cognito identifiers from
OpenTofu outputs, synchronizes the bundle, and creates a CloudFront invalidation.
No credential or secret is embedded in the bundle.

Allow exactly two browser origins through API Gateway CORS: the deployed
CloudFront HTTPS origin and the fixed localhost development origin. Continue to
require Cognito JWT authorization on every application route; CORS is not an
authorization control.

## Consequences

- The S3 bucket cannot be read directly or anonymously.
- CloudFront provides HTTPS and SPA routing without a server or custom-domain
  dependency.
- Local browser development remains usable against the deployed API.
- Asset deployment is an explicit AWS mutation independent of an OpenTofu plan.
- The development distribution and bucket are disposable with the application
  stack; CloudFront creation and teardown can take several minutes.
- A custom domain, alternate certificate, or web application firewall requires
  a separate measured need and reviewed design change.
