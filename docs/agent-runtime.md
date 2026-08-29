# Agent loop and tool integration

Praxis uses one Strands agent to turn a project-planning goal into exactly three
structured, evidence-backed candidates. The agent is hosted by AgentCore Runtime,
uses Amazon Nova Micro through Bedrock, and reaches catalog data only through the
IAM-authenticated AgentCore Gateway.

## Loop

```text
validated user goal
        |
        v
Strands Agent -----------> Bedrock Converse (Nova Micro)
        ^                            |
        |                            | tool request
        |                            v
        +--- structured tool result--MCPClient + SigV4
                                     |
                                     v
                              AgentCore Gateway
                                     |
                                     v
                               catalog Lambda
                                     |
                                     v
                                  DynamoDB

final model output -> ProjectCandidateSet validation -> evidence-ID grounding check
```

Strands owns the model/tool cycle: it sends the user goal and system instructions
to Bedrock, executes a selected MCP tool, returns that tool's structured result to
the model, and repeats until the model produces the requested candidate set or a
configured limit stops the run. The Bedrock model provider uses the Bedrock
Converse API rather than a provider-specific message format.

The Runtime integration will give Strands an `MCPClient` backed by a
streamable-HTTP transport that signs each Gateway request for the
`bedrock-agentcore` service. The MCP client must remain open while Strands lists
and calls tools. Tool names and schemas come from Gateway discovery; the strict
Pydantic contracts and Lambda validation documented in ADR 0003 remain the
authoritative boundary.

AWS documents the supported Strands `MCPClient` lifecycle in its
[Gateway agent integration guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-agent-integration.html).
Praxis uses IAM rather than the bearer-token variant shown there; the signed
transport follows the IAM pattern in the
[Bedrock Gateway integration guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-gateway-target.html).

## Evidence boundary

- Tool results are retrieved facts and retain stable `evidence_id` values.
- Candidate titles, rationales, connections, and milestones are generated
  recommendations and must not be represented as retrieved facts.
- Every candidate must cite at least one evidence ID returned during its run.
- Final Pydantic validation rejects the wrong candidate count or malformed output.
- A grounding check rejects citations that were not returned by a tool in the
  current run.
- Catalog records are untrusted data and cannot override system instructions.

## Lifecycle and isolation

The runtime adapter owns model, MCP, and Strands construction. An MCP connection
may be reused only inside its AgentCore Runtime session; it must never become a
cross-session conversation store. AgentCore Runtime assigns sessions isolated
execution environments. AgentCore Memory stores long-lived preferences and
decisions, while authoritative catalog records remain in DynamoDB.

Each invocation returns a buffered structured response. Streaming, multi-agent
orchestration, and cross-session in-process state are outside the MVP. The
[AgentCore Runtime lifecycle documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
describes the service's session and immutable-version boundaries.

## Local and deployed paths

The local planner retrieves from `InMemoryCatalog` before the model call, which
keeps development and evaluation usable without AWS. The deployed agent gives
`create_agent` a Gateway-backed MCP tool provider. Explicit tool/result budgets,
the AgentCore Runtime entry point, container packaging, and session-isolation
tests complete the runtime boundary without removing the local path.
