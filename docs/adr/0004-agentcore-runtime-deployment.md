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
  configured Nova Micro foundation model and catalog Gateway, write AgentCore
  Runtime logs, and send trace segments and sampling telemetry to X-Ray. It
  receives no catalog storage or ingestion access.
- Environment variables carry the model, Gateway endpoint, and bounded tool and
  result limits. Development sessions idle out after five minutes and have a
  maximum lifetime of one hour.
- The container starts through the AWS Distro for OpenTelemetry auto-instrumentor.
  Strands emits its native `strands.telemetry.tracer` spans; AgentCore supplies
  the Runtime endpoint service name and propagates the Runtime session ID. This
  keeps traces compatible with AgentCore Evaluations without an application-
  specific trace schema.
- An apply-time script calls `UpdateAgentRuntime` with MMDSv2 required, waits for
  `READY`, and verifies the reported setting. OpenTofu reruns it only when the
  declared runtime configuration changes. Remove this compatibility resource
  when the AWS provider can manage `metadataConfiguration` directly.
- A named `stable` endpoint targets an explicit Runtime version. It never
  follows the service-managed `DEFAULT` endpoint automatically. Promote a new
  version only after its MMDSv2 setting and Runtime status are verified.

## Consequences

- Every deployment is tied to a reviewed, content-addressed image.
- Runtime credentials cannot bypass the Gateway to read catalog storage.
- Trace payloads can include prompts, responses, and tool inputs and outputs;
  CloudWatch access and retention therefore form part of the application data
  boundary.
- Creating or changing the Runtime produces one additional Runtime version for
  the mandatory MMDSv2 update.
- Runtime updates leave the application endpoint on its prior version until a
  separately reviewed configuration change promotes the verified replacement.
- The AWS CLI and `jq` must be present where a user runs the guarded OpenTofu
  apply.
