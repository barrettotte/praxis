# ADR 0001: Initial architecture

- Status: Accepted
- Date: 2026-08-18

## Context

Praxis must search a small personal catalog, propose three evidence-backed
project candidates, and turn a selection into a scoped project brief. The MVP
is a single-user demonstration with a total AWS cost target below $10. It must
remain usable locally before deployment, exclude external writes, and keep its
source datasets reproducible and authoritative outside AWS.

## Decision

Praxis will use a serverless, single-agent architecture in `us-east-1`:

```text
React + TypeScript -> Cognito -> API Gateway -> API Lambda
                                             -> AgentCore Runtime
                                                |-- Strands agent
                                                |-- Bedrock model
                                                `-- AgentCore Memory
                                             -> AgentCore Gateway (MCP)
                                                `-- least-privilege Lambda tools
                                                    -> DynamoDB / S3
```

- API Gateway is the public application boundary. Arbitrary public clients may
  not invoke AgentCore Runtime directly.
- AgentCore Gateway is the secured MCP tool boundary. Tools use strict schemas,
  bounded responses, and separate least-privilege execution roles.
- The Python agent uses Strands Agents SDK on AgentCore Runtime. Amazon Nova
  Micro (`amazon.nova-micro-v1:0`) is the initial on-demand model, read from
  configuration rather than embedded in application code.
- React and TypeScript live in this repository. The initial API buffers complete
  responses; streaming can be added after the workflow is stable.
- OpenTofu with the AWS provider manages infrastructure. The initial topology
  has no VPC, NAT gateway, or provisioned throughput.
- Source JSON remains read-only in the sibling repository. Ingested S3 and
  DynamoDB copies are disposable, reproducible, and retain provenance.
- The MVP and roadmap expose only read-only tools and separate retrieved facts
  from generated recommendations. External writes are outside product scope.
- AgentCore Memory may retain preferences and prior decisions, but not the
  authoritative catalog. No multi-agent orchestration is part of the MVP.
- Development-account access is documented in `docs/account-setup.md`; its broad
  human permission is not the workload permission model.

## Consequences

- Local catalog and agent interfaces must have implementations that do not
  require deployed AWS resources.
- Workload identities, APIs, and tool responses have explicit security
  boundaries that can be tested independently.
- A serverless design minimizes idle cost and makes temporary development stacks
  practical, at the expense of cold starts and AWS service integration work.
- Buffered responses simplify the first release but provide less interactive
  feedback than streaming.
- A VPC, stronger default model, Knowledge Base, streaming, or
  multi-agent design requires measured need and a superseding ADR.
