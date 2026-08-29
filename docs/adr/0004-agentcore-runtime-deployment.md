# ADR 0004: AgentCore Runtime deployment

- Status: Accepted
- Date: 2026-08-29

## Context

The Strands agent requires managed hosting that preserves its IAM-authenticated
Gateway tool boundary, remains inexpensive while idle, and can reproduce an
exact reviewed container deployment. AgentCore Runtime requires MMDSv2 for
invocations, but the AWS provider resource does not expose the Runtime
`metadataConfiguration` field supported by `UpdateAgentRuntime`.

## Decision

- OpenTofu creates an IAM-authenticated AgentCore Runtime in `PUBLIC` network
  mode. IAM authorization protects the service endpoint; `PUBLIC` describes
  outbound network connectivity and does not make invocation anonymous.
- The runtime consumes an ECR image by digest. The repository's immutable tags
  remain useful for publication and inspection, but deployment identity is the
  OCI digest.
- The execution role can pull only the agent repository, invoke only the
  configured Nova Micro foundation model and catalog Gateway, and write only
  AgentCore Runtime logs. It receives no catalog storage or ingestion access.
- Environment variables carry the model, Gateway endpoint, and bounded tool and
  result limits. Development sessions idle out after five minutes and have a
  maximum lifetime of one hour.
- An apply-time script calls `UpdateAgentRuntime` with MMDSv2 required, waits for
  `READY`, and verifies the reported setting. OpenTofu reruns it only when the
  declared runtime configuration changes. Remove this compatibility resource
  when the AWS provider can manage `metadataConfiguration` directly.

## Consequences

- Every deployment is tied to a reviewed, content-addressed image.
- Runtime credentials cannot bypass the Gateway to read catalog storage.
- Creating or changing the Runtime produces one additional Runtime version for
  the mandatory MMDSv2 update.
- The AWS CLI and `jq` must be present where a user runs the guarded OpenTofu
  apply.
